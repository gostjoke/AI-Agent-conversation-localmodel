@echo off
title AI Agent Conversation Launcher
color 0A

echo.
echo  ============================================
echo   AI Agent Conversation - Startup Script
echo  ============================================
echo.

REM ── Step 1: Check Python ──────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+
    echo         https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python found

REM ── Step 2: Install dependencies ─────────────────────────
echo.
echo [INFO] Installing Python dependencies...
pip install -r backend\requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)
echo [OK] Dependencies ready

REM ── Step 3: Check Ollama ──────────────────────────────────
echo.
ollama list >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Ollama not found in PATH.
    echo           Please install Ollama from https://ollama.com/download
    echo           and run: ollama pull gemma3:4b
    echo.
    echo           Starting backend anyway (it will show status on the UI)...
) else (
    echo [OK] Ollama found
    REM Pull model if not present
    echo [INFO] Checking model gemma3:4b...
    ollama list | find "gemma3:4b" >nul 2>&1
    if errorlevel 1 (
        echo [INFO] Pulling gemma3:4b (this may take a few minutes)...
        ollama pull gemma3:4b
    ) else (
        echo [OK] Model gemma3:4b is ready
    )
)

REM ── Step 4: Start Ollama server (if not running) ──────────
echo.
echo [INFO] Ensuring Ollama server is running...
curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo [INFO] Starting Ollama server...
    start "Ollama Server" /min ollama serve
    timeout /t 3 /nobreak >nul
)
echo [OK] Ollama server ready

REM ── Step 5: Start backend ────────────────────────────────
echo.
echo [INFO] Starting FastAPI backend on http://localhost:8000 ...
start "AI Agent Backend" cmd /k "cd /d %~dp0 && python backend\main.py"
timeout /t 2 /nobreak >nul

REM ── Step 6: Open frontend in browser ────────────────────
echo.
echo [INFO] Opening frontend in browser...
start "" "%~dp0frontend\index.html"

echo.
echo  ============================================
echo   Everything is running!
echo.
echo   Backend : http://localhost:8000
echo   Frontend: frontend\index.html (opened in browser)
echo   API docs: http://localhost:8000/docs
echo  ============================================
echo.
echo  Close the "AI Agent Backend" window to stop.
echo.
pause
