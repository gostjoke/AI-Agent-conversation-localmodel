try to save the token usage.

## Structure
- backend/main.py — FastAPI: /api/chat (SSE), /api/models, /api/tools, /ws/conversation, serves frontend/dist
- backend/assistant.py — Ollama tool-calling agent loop (events: thinking/token/tool_start/tool_end/notice/done/error)
- backend/tools.py — @tool registry; sandbox = backend/workspace (AGENT_WORKSPACE)
- backend/agents.py — debate personas
- backend/rag.py — RAG tools (search_docs/list_doc_sources/index_documents): Postgres tsvector(jieba+CJK bigram) + pgvector, RRF, optional bge-reranker; RAG_MODE keyword|hybrid; CLI ingest/embed/search
- frontend/ — Vite + React 19 (JSX) + antd 6 + @ant-design/x 2 (Bubble, Sender, Conversations, ThoughtChain, Think)
- Run: setup.bat once, start.bat (http://localhost:8000), dev.bat (hot reload :5173)
