@echo off
title Local AI Agent
cd /d %~dp0

REM Start Ollama if not running 若 Ollama 未啟動則啟動
curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
  echo [INFO] Starting Ollama...
  start "Ollama" /min ollama serve
  timeout /t 3 /nobreak >nul
)

REM RAG database (pgvector) 啟動資料庫；沒有 Docker 則 RAG 自動停用
if not defined DATABASE_URL set DATABASE_URL=postgresql://agent:agent@localhost:5432/agent
docker --version >nul 2>&1 && docker compose up -d db >nul 2>&1

REM Build frontend if missing 若無打包檔則先打包
if not exist frontend\dist\index.html (
  pushd frontend & call npm run build & popd
)

start "AI Agent Backend" cmd /k "python backend\main.py"
timeout /t 3 /nobreak >nul
start "" http://localhost:8000
echo Running at http://localhost:8000  (close the backend window to stop 關閉後端視窗即停止)
