@echo off
title Local AI Agent (dev)
cd /d %~dp0
REM Hot-reload dev mode: backend :8000 + Vite :5173  開發模式（前端熱更新）
start "AI Agent Backend" cmd /k "python backend\main.py"
start "Vite Dev" cmd /k "cd frontend && npm run dev"
timeout /t 4 /nobreak >nul
start "" http://localhost:5173
