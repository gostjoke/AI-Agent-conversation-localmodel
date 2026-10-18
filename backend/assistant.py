"""
Assistant agent: Ollama chat + tool-calling loop, streamed as events.
助手 Agent：Ollama 對話 + 工具呼叫迴圈，以事件串流回前端。

Event types 事件類型:
  thinking {delta}         model reasoning (qwen3 / deepseek-r1)  模型思考過程
  token    {delta}         answer text                            回答文字
  tool_start {id,name,args}                                       開始呼叫工具
  tool_end   {id,name,result}                                     工具結果
  notice   {message}       e.g. model has no tool support         提示訊息
  done / error
"""

import asyncio
import json
import logging
from typing import AsyncIterator

import httpx

from tools import run_tool, tool_schemas

log = logging.getLogger(__name__)

MAX_STEPS = 6  # max tool rounds per user message 每則訊息最多工具回合數

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful local AI assistant for an IT specialist in electronics manufacturing. "
    "Answer concisely. Use tools when they help (time, math, files in the workspace); "
    "for questions about internal documents/SOPs call search_docs, and search again with refined "
    "keywords (synonyms, English/Chinese, exact codes) if results are weak; cite [source#chunk]. "
    "never invent tool results. Reply in the user's language (繁體中文 if the user writes Chinese)."
)


async def _stream_chat(client: httpx.AsyncClient, url: str, payload: dict) -> AsyncIterator[dict]:
    async with client.stream("POST", url, json=payload) as r:
        if r.status_code >= 400:
            body = (await r.aread()).decode(errors="replace")
            raise httpx.HTTPStatusError(body, request=r.request, response=r)
        async for line in r.aiter_lines():
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


async def run_assistant(
    base_url: str,
    model: str,
    messages: list[dict],
    system_prompt: str | None = None,
    tools: list[str] | None = None,
    think: bool = False,
    temperature: float = 0.7,
    timeout: float = 300.0,
) -> AsyncIterator[dict]:
    convo = [{"role": "system", "content": system_prompt or DEFAULT_SYSTEM_PROMPT}]
    convo += [{"role": m["role"], "content": m.get("content", "")}
              for m in messages if m.get("role") in ("user", "assistant") and m.get("content")]

    schemas = tool_schemas(tools) if tools != [] else []
    use_think = think
    call_seq = 0

    async with httpx.AsyncClient(timeout=timeout) as client:
        step = 0
        while step < MAX_STEPS:
            payload = {
                "model": model,
                "messages": convo,
                "stream": True,
                "options": {"temperature": temperature},
            }
            if schemas:
                payload["tools"] = schemas
            if use_think:
                payload["think"] = True

            content, tool_calls = "", []
            try:
                async for chunk in _stream_chat(client, f"{base_url}/api/chat", payload):
                    if chunk.get("error"):
                        raise RuntimeError(chunk["error"])
                    msg = chunk.get("message", {})
                    if msg.get("thinking"):
                        yield {"type": "thinking", "delta": msg["thinking"]}
                    if msg.get("content"):
                        content += msg["content"]
                        yield {"type": "token", "delta": msg["content"]}
                    tool_calls += msg.get("tool_calls") or []
            except httpx.HTTPStatusError as e:
                err = str(e).lower()
                # Graceful fallback 自動降級: model lacks tools / thinking support
                if schemas and "does not support tools" in err:
                    schemas = []
                    yield {"type": "notice", "message": f"{model} 不支援工具呼叫 (no tool support) — tools disabled"}
                    continue
                if use_think and "does not support thinking" in err:
                    use_think = False
                    yield {"type": "notice", "message": f"{model} 不支援思考模式 (no thinking support)"}
                    continue
                raise RuntimeError(f"Ollama error {e.response.status_code}: {e}") from None

            if not tool_calls:
                yield {"type": "done"}
                return

            # Execute tools, feed results back 執行工具並回填結果給模型
            convo.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
            for tc in tool_calls:
                fn = tc.get("function", {})
                name, args = fn.get("name", ""), fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                call_seq += 1
                cid = f"call_{call_seq}"
                yield {"type": "tool_start", "id": cid, "name": name, "args": args}
                # thread: DB / reranker tools must not block the event loop 避免阻塞事件迴圈
                result = await asyncio.to_thread(run_tool, name, args)
                log.info("tool %s(%s) -> %s", name, args, result[:120])
                yield {"type": "tool_end", "id": cid, "name": name, "result": result}
                convo.append({"role": "tool", "tool_name": name, "content": result})
            step += 1

        yield {"type": "notice", "message": f"Reached max tool steps ({MAX_STEPS}) 已達工具呼叫上限"}
        yield {"type": "done"}
