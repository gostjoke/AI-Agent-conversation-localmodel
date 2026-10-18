@echo off
title AI Agent Setup
cd /d %~dp0
echo ============================================
echo   Local AI Agent - First-Time Setup 首次安裝
echo ============================================

python --version >nul 2>&1 || (echo [ERROR] Python 3.10+ required: https://www.python.org/downloads/ & pause & exit /b 1)
echo [OK] Python found
pip install -r backend\requirements.txt || (echo [ERROR] pip install failed & pause & exit /b 1)

node --version >nul 2>&1 || (echo [ERROR] Node.js 20+ required: https://nodejs.org/ & pause & exit /b 1)
echo [OK] Node.js found
pushd frontend
call npm install || (echo [ERROR] npm install failed & popd & pause & exit /b 1)
call npm run build || (echo [ERROR] build failed & popd & pause & exit /b 1)
popd
echo [OK] Frontend built (frontend\dist)

ollama --version >nul 2>&1
if errorlevel 1 (
  echo [WARNING] Ollama not installed: https://ollama.com/download/windows
) else (
  echo [INFO] Pulling models 下載模型 ...
  ollama pull qwen3:8b
  ollama pull gemma3:4b
)
echo.
echo Setup complete. Run start.bat  安裝完成，請執行 start.bat
pause
