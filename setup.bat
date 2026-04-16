@echo off
title AI Agent Setup
color 0B

echo.
echo  ============================================
echo   AI Agent Conversation - First-Time Setup
echo  ============================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.10+ is required.
    echo         Download at: https://www.python.org/downloads/
    echo         Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do echo [OK] %%i

REM Install deps
echo.
echo [INFO] Installing Python packages (fastapi, uvicorn, httpx)...
pip install fastapi "uvicorn[standard]" httpx websockets
if errorlevel 1 (
    echo [ERROR] pip install failed. Try running as Administrator.
    pause
    exit /b 1
)
echo [OK] Python packages installed

REM Check Ollama
echo.
ollama --version >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Ollama is not installed.
    echo.
    echo  Please:
    echo   1. Download Ollama from https://ollama.com/download/windows
    echo   2. Install it (it adds itself to PATH)
    echo   3. Run this setup again  -OR-  run: ollama pull gemma3:4b
    echo.
) else (
    for /f "tokens=*" %%i in ('ollama --version') do echo [OK] %%i
    echo [INFO] Pulling gemma3:4b model (may take several minutes)...
    ollama pull gemma3:4b
    echo [OK] Model ready
)

echo.
echo  ============================================
echo   Setup complete!
echo   Run start.bat to launch the application.
echo  ============================================
echo.
pause
