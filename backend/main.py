"""
AI Agent backend — FastAPI.
AI Agent 後端 —— FastAPI。

  POST /api/chat          Assistant agent, SSE stream   助手 agent（SSE 串流）
  GET  /api/models        Installed Ollama models       已安裝模型
  GET  /api/tools         Available agent tools         可用工具
  GET  /health            Ollama status                 Ollama 狀態
  WS   /ws/conversation   3-agent debate                三人辯論
  /                       React build (frontend/dist)   前端打包檔
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents import AGENTS, build_agent_prompt
from assistant import DEFAULT_SYSTEM_PROMPT, run_assistant
from tools import WORKSPACE, tool_list
import rag  # noqa: E402

# ── Configuration 設定（可用環境變數覆蓋）────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
ASSISTANT_MODEL = os.getenv("ASSISTANT_MODEL", "qwen3:8b")   # needs tool support 需支援工具
DEBATE_MODEL = os.getenv("DEBATE_MODEL", "gemma3:4b")
DEFAULT_ROUNDS = 3
REQUEST_TIMEOUT = 300.0
PORT = int(os.getenv("PORT", "8000"))
DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

RAG_ENABLED = rag.register_tools()  # search_docs etc. if DATABASE_URL reachable 連得到 DB 才啟用

app = FastAPI(title="Local AI Agent", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def no_cache_html(request, call_next):
    """index.html never cached → new builds show immediately; hashed /assets/ can cache.
    首頁不快取，重新打包後立即生效；/assets/ 檔名含 hash 可快取。"""
    resp = await call_next(request)
    if not request.url.path.startswith(("/assets/", "/api/")):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


# ── Ollama helpers ────────────────────────────────────────────────────────────

async def ollama_models() -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            r.raise_for_status()
            models = [{"name": m["name"], "size": m.get("size", 0),
                       "family": m.get("details", {}).get("family", ""),
                       "params": m.get("details", {}).get("parameter_size", "")}
                      for m in r.json().get("models", [])]
            return {"ollama_running": True, "models": models}
        except Exception as e:
            return {"ollama_running": False, "models": [], "error": str(e)}


def _has_model(models: list[dict], name: str) -> bool:
    return any(m["name"] == name or m["name"].split(":")[0] == name for m in models)


async def stream_ollama_response(messages: list[dict], model: str) -> AsyncIterator[str]:
    payload = {"model": model, "messages": messages, "stream": True,
               "options": {"temperature": 0.8, "top_p": 0.9, "num_predict": 300}}
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        async with client.stream("POST", f"{OLLAMA_BASE_URL}/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                token = data.get("message", {}).get("content", "")
                if token:
                    yield token
                if data.get("done"):
                    break


# ── REST ──────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    s = await ollama_models()
    return {"status": "ok", "ollama": {**s, "assistant_model": ASSISTANT_MODEL,
                                       "assistant_ready": _has_model(s["models"], ASSISTANT_MODEL)}}


@app.get("/api/models")
async def api_models():
    s = await ollama_models()
    return {**s, "default_assistant": ASSISTANT_MODEL, "default_debate": DEBATE_MODEL}


@app.get("/api/tools")
async def api_tools():
    return {"tools": tool_list(), "workspace": str(WORKSPACE), "rag": RAG_ENABLED and rag.RAG_MODE,
            "default_system_prompt": DEFAULT_SYSTEM_PROMPT}


@app.get("/agents")
async def list_agents():
    return {"agents": [{k: a[k] for k in ("id", "name", "role", "color", "avatar")} for a in AGENTS]}


class ChatRequest(BaseModel):
    messages: list[dict]                 # [{role: user|assistant, content}]
    model: str | None = None
    system_prompt: str | None = None
    tools: list[str] | None = None       # None = all, [] = none 全部 / 不使用
    think: bool = False
    temperature: float = 0.7


@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    """SSE stream: each line `data: {json event}`. 每行一個 JSON 事件。"""
    async def gen():
        try:
            async for ev in run_assistant(
                OLLAMA_BASE_URL, req.model or ASSISTANT_MODEL, req.messages,
                req.system_prompt, req.tools, req.think, req.temperature, REQUEST_TIMEOUT,
            ):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except httpx.ConnectError:
            yield f"data: {json.dumps({'type': 'error', 'message': '本地模型未啟動 Local model not running (ollama serve)'})}\n\n"
        except Exception as e:
            log.error("chat error: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── WebSocket debate 辯論 ─────────────────────────────────────────────────────

@app.websocket("/ws/conversation")
async def conversation_ws(websocket: WebSocket):
    await websocket.accept()
    try:
        payload = json.loads(await websocket.receive_text())
        topic = payload.get("topic", "").strip()
        rounds = max(1, min(int(payload.get("rounds", DEFAULT_ROUNDS)), 10))
        model = payload.get("model") or DEBATE_MODEL

        if not topic:
            await websocket.send_json({"type": "error", "message": "Topic cannot be empty."})
            return
        s = await ollama_models()
        if not s["ollama_running"]:
            await websocket.send_json({"type": "error", "message": "本地模型未啟動 Local model not running."})
            return
        if not _has_model(s["models"], model):
            await websocket.send_json({"type": "error", "message": f"Model '{model}' not found. Run: ollama pull {model}"})
            return

        meta = lambda a: {k: a[k] for k in ("id", "name", "role", "color", "avatar")}
        await websocket.send_json({"type": "start", "topic": topic, "rounds": rounds,
                                   "agents": [meta(a) for a in AGENTS]})
        history: list[dict] = []
        for rnd in range(1, rounds + 1):
            await websocket.send_json({"type": "round", "round": rnd, "total": rounds})
            for agent in AGENTS:
                await websocket.send_json({"type": "agent_start", "agent_id": agent["id"], "round": rnd, **meta(agent)})
                full = ""
                try:
                    async for token in stream_ollama_response(build_agent_prompt(agent, topic, history), model):
                        full += token
                        await websocket.send_json({"type": "token", "agent_id": agent["id"], "token": token})
                except Exception as e:
                    await websocket.send_json({"type": "error", "message": f"{agent['name']}: {e}"})
                    return
                history.append({"agent_id": agent["id"], "name": agent["name"],
                                "role": agent["role"], "content": full.strip()})
                await websocket.send_json({"type": "agent_done", "agent_id": agent["id"], "content": full.strip()})
                await asyncio.sleep(0.3)
        await websocket.send_json({"type": "done", "total_turns": len(history)})
    except WebSocketDisconnect:
        log.info("WebSocket disconnected")
    except Exception as e:
        log.error("WS error: %s", e, exc_info=True)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


# ── Serve React build 提供前端打包檔 (after `npm run build`) ──────────────────
if DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    os.chdir(Path(__file__).parent)
    uvicorn.run("main:app", host="127.0.0.1", port=PORT, reload=False, log_level="info")
