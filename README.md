# Local AI Agent (Ollama)

本地 LLM 助手 Agent + 三人辯論，全部在本機 Ollama 執行。
A local LLM assistant agent with tool calling, plus a 3-agent debate — 100% on your machine via Ollama.

**Stack:** FastAPI · Ollama · React 19 · antd 6 · [Ant Design X](https://x.ant.design) (antd 官方 AI 介面元件)

---

## Features 功能

| | 中文 | English |
|---|---|---|
| 💬 助手 | 串流回答、Markdown/表格/程式碼高亮 | Streaming answers, Markdown, code highlight |
| 🛠 工具 | Agent 自動呼叫工具：時間、計算機、讀/寫沙盒檔案 | Tool-calling loop: time, calculator, sandbox file read/write |
| 🧠 思考 | 顯示 qwen3 / deepseek-r1 推理過程 | Shows model reasoning (thinking mode) |
| 🗂 對話 | 多對話、重新命名、刪除、本機保存 | Multiple chats, rename/delete, saved in browser |
| ⚙ 設定 | 切換模型、溫度、工具、系統提示詞 | Model, temperature, tools, system prompt |
| 🗣 辯論 | Alex / Jordan / Morgan 三人辯論 | 3-agent debate (original feature) |

## Requirements 需求

Windows 10/11 · Python 3.10+ · Node.js 20+ · [Ollama](https://ollama.com/download/windows)

Model 模型: `qwen3:8b`（助手，支援工具+思考 / assistant, tools + thinking）, `gemma3:4b`（辯論 / debate）.
RTX 5070/5080 可跑 `qwen3:14b`。Other tool-capable models: `llama3.1:8b`, `mistral-nemo`, `qwen2.5:7b`.

## Run 啟動

```bat
setup.bat   :: 首次：pip + npm install + build + pull models
start.bat   :: 日常：http://localhost:8000
dev.bat     :: 開發：熱更新 hot reload http://localhost:5173
```

Manual 手動:
```bash
pip install -r backend/requirements.txt
cd frontend && npm install && npm run build && cd ..
python backend/main.py          # → http://localhost:8000
```

## Docker 部署 (Nginx + FastAPI)

```
Browser ─► :8080 Nginx (frontend container: React dist + reverse proxy)
              ├─ /api, /health ─► backend:8000 (FastAPI)   SSE 已關閉緩衝 buffering off
              └─ /ws/          ─► backend:8000 (WebSocket)
backend ─► Ollama  (host 主機 / or ollama container 容器)
```

```bash
cp .env.example .env                       # optional 選用
docker compose up -d --build               # 使用主機 Ollama → http://localhost:8080
docker compose --profile gpu up -d --build # Ollama 也跑在容器（NVIDIA GPU）
docker compose exec ollama ollama pull qwen3:8b   # gpu profile 首次下載模型
docker compose logs -f backend             # 看後端 log
docker compose down                        # 停止
```

| File 檔案 | 說明 |
|---|---|
| `backend/Dockerfile` | python:3.12-slim, non-root user, healthcheck |
| `frontend/Dockerfile` | Multi-stage 多階段: node build → nginx:alpine |
| `frontend/nginx.conf` | SPA fallback, gzip, asset cache, SSE + WS proxy |
| `docker-compose.yml` | frontend / backend / ollama(profile `gpu`) |
| `.env.example` | Port, Ollama URL, models 埠、Ollama 位址、模型 |

Notes 注意:
- 只有 Nginx 對外開放 port，後端不直接暴露。Only Nginx is published; backend stays on the internal network.
- **主機 Ollama 連不到 (Ollama offline)**：Windows 預設只聽 127.0.0.1。設定系統環境變數 `OLLAMA_HOST=0.0.0.0` 後重啟 Ollama。Set `OLLAMA_HOST=0.0.0.0` and restart Ollama.
- **gpu profile** 需要 Docker Desktop (WSL2) + NVIDIA 驅動；`.env` 設 `OLLAMA_BASE_URL=http://ollama:11434`。
- 沙盒檔案存在 volume `agent-workspace`。Sandbox files persist in the `agent-workspace` volume.
- 開放給其他人用前請加上登入驗證（目前無 auth）。Add auth before exposing beyond your LAN — there is none yet.

## Structure 結構

```
backend/
  main.py        FastAPI: /api/chat (SSE), /api/models, /api/tools, /health, /ws/conversation
  assistant.py   Agent loop 代理迴圈: Ollama /api/chat + tools → run → feed back → answer
  tools.py       Tool registry 工具註冊 (@tool decorator)
  agents.py      Debate personas 辯論角色
  workspace/     Sandbox folder for file tools 檔案工具沙盒（自動建立）
frontend/
  src/App.jsx                 Layout, theme, status 版面/主題/狀態
  src/pages/ChatPage.jsx      Assistant chat 助手對話
  src/pages/DebatePage.jsx    Debate 辯論
  src/components/             Markdown, Settings drawer
  src/api.js                  SSE stream client 串流客戶端
```

## How the agent works 運作方式

```
User ─► React (Sender) ─POST /api/chat─► FastAPI ─► Ollama (model + tool schemas)
                ▲                                          │
                │  SSE events: thinking/token/tool_*       ▼
                └──────────────────────────────  tool_calls? → run_tool() → append result → loop (≤6)
```

## Add your own tool 新增自訂工具

Edit `backend/tools.py` 編輯 `backend/tools.py`:

```python
@tool("query_po", "Look up a purchase order by PO number.",   # description: model reads this 模型依此決定何時呼叫
      {"po": {"type": "string", "description": "PO number"}}, ["po"], label="查詢 PO")
def query_po(po: str) -> str:
    # e.g. pyodbc → SQL Server; return text/CSV 回傳文字或 CSV
    return "..."
```

Restart backend → tool appears in Settings automatically. 重啟後端即自動出現在設定中。

## Config 設定（environment variables 環境變數）

| Var | Default | 說明 |
|---|---|---|
| `ASSISTANT_MODEL` | `qwen3:8b` | 助手預設模型 |
| `DEBATE_MODEL` | `gemma3:4b` | 辯論模型 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 位址 |
| `AGENT_WORKSPACE` | `backend/workspace` | 檔案工具沙盒 |
| `PORT` | `8000` | 後端埠 |

## Security 安全

Backend binds to `127.0.0.1` only. File tools cannot leave the workspace folder.
後端只監聽本機；檔案工具無法存取沙盒以外的路徑。

## Troubleshooting 疑難排解

- **後端離線 Backend offline** → run `python backend/main.py`
- **Ollama offline** → `ollama serve`
- **「不支援工具」notice** → model has no tool support; pick qwen3 / llama3.1 模型不支援工具，請換模型
- **Blank page at :8000** → run `npm run build` in `frontend/`

## License

See [LICENSE](LICENSE).
