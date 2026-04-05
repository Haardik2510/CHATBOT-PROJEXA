@echo off
echo ========================================
echo SET Academic Chatbot Backend Server
echo ========================================
echo.

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Check if Ollama is running
echo Checking Ollama connection...
curl -s http://127.0.0.1:11434/api/tags >nul 2>&1
if %errorlevel% neq 0 (
    echo WARNING: Ollama is not running. The chatbot will use fallback mode.
    echo To enable AI responses, start Ollama with: ollama serve
    echo.
)

echo Starting FastAPI server on http://localhost:8001
echo.
python server.py
