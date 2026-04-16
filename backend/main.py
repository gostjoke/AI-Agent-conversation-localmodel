"""
AI Agent Conversation Backend
FastAPI + WebSocket server that orchestrates multi-agent discussions via Ollama.
"""

import asyncio
import json
import logging
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from agents import AGENTS, build_agent_prompt

# ── Configuration ────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = "http://localhost:11434"
MODEL_NAME = "gemma3:4b"
DEFAULT_ROUNDS = 3          # How many full rounds (each agent speaks once per round)
REQUEST_TIMEOUT = 120.0     # seconds

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="AI Agent Conversation", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Ollama helpers ────────────────────────────────────────────────────────────

async def check_ollama() -> dict:
    """Check if Ollama is running and the model is available."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            model_ready = any(MODEL_NAME in m for m in models)
            return {"ollama_running": True, "model_ready": model_ready, "models": models}
        except Exception as e:
            return {"ollama_running": False, "model_ready": False, "error": str(e)}


async def stream_ollama_response(messages: list[dict]) -> AsyncIterator[str]:
    """Stream a response from Ollama token by token."""
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": True,
        "options": {
            "temperature": 0.8,
            "top_p": 0.9,
            "num_predict": 300,
        },
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        async with client.stream(
            "POST",
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    token = data.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if data.get("done"):
                        break
                except json.JSONDecodeError:
                    continue


# ── REST endpoints ────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    status = await check_ollama()
    return {"status": "ok", "ollama": status}


@app.get("/agents")
async def list_agents():
    return {"agents": [
        {"id": a["id"], "name": a["name"], "role": a["role"], "color": a["color"], "avatar": a["avatar"]}
        for a in AGENTS
    ]}


# ── WebSocket conversation endpoint ──────────────────────────────────────────

@app.websocket("/ws/conversation")
async def conversation_ws(websocket: WebSocket):
    await websocket.accept()
    log.info("WebSocket connected")

    try:
        # Receive the start payload from client
        raw = await websocket.receive_text()
        payload = json.loads(raw)
        topic = payload.get("topic", "").strip()
        rounds = int(payload.get("rounds", DEFAULT_ROUNDS))
        rounds = max(1, min(rounds, 10))  # clamp 1-10

        if not topic:
            await websocket.send_json({"type": "error", "message": "Topic cannot be empty."})
            return

        # Check Ollama availability
        status = await check_ollama()
        if not status["ollama_running"]:
            await websocket.send_json({
                "type": "error",
                "message": "Ollama is not running. Please start Ollama and try again.",
            })
            return
        if not status["model_ready"]:
            await websocket.send_json({
                "type": "error",
                "message": f"Model '{MODEL_NAME}' not found. Run: ollama pull {MODEL_NAME}",
            })
            return

        # Notify client that we're starting
        await websocket.send_json({
            "type": "start",
            "topic": topic,
            "rounds": rounds,
            "agents": [
                {"id": a["id"], "name": a["name"], "role": a["role"],
                 "color": a["color"], "avatar": a["avatar"]}
                for a in AGENTS
            ],
        })

        history: list[dict] = []

        for round_num in range(1, rounds + 1):
            await websocket.send_json({"type": "round", "round": round_num, "total": rounds})

            for agent in AGENTS:
                # Signal that this agent is about to speak
                await websocket.send_json({
                    "type": "agent_start",
                    "agent_id": agent["id"],
                    "name": agent["name"],
                    "role": agent["role"],
                    "color": agent["color"],
                    "avatar": agent["avatar"],
                    "round": round_num,
                })

                messages = build_agent_prompt(agent, topic, history)
                full_response = ""

                try:
                    async for token in stream_ollama_response(messages):
                        full_response += token
                        await websocket.send_json({
                            "type": "token",
                            "agent_id": agent["id"],
                            "token": token,
                        })
                except Exception as e:
                    log.error(f"Error streaming from Ollama: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Error generating response for {agent['name']}: {str(e)}",
                    })
                    return

                # Save to history
                history.append({
                    "agent_id": agent["id"],
                    "name": agent["name"],
                    "role": agent["role"],
                    "content": full_response.strip(),
                })

                await websocket.send_json({
                    "type": "agent_done",
                    "agent_id": agent["id"],
                    "content": full_response.strip(),
                })

                # Small pause between agents for readability
                await asyncio.sleep(0.5)

        # Conversation complete
        await websocket.send_json({
            "type": "done",
            "message": "Discussion complete.",
            "total_turns": len(history),
        })
        log.info(f"Conversation finished: {len(history)} turns on topic '{topic}'")

    except WebSocketDisconnect:
        log.info("WebSocket disconnected by client")
    except Exception as e:
        log.error(f"Unexpected error: {e}", exc_info=True)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
