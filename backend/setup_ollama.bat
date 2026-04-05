@echo off
echo ========================================
echo Ollama Setup for SET Academic Chatbot
echo ========================================
echo.

REM Check if Ollama is installed
where ollama >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Ollama is not installed!
    echo.
    echo Please install Ollama from: https://ollama.com/
    echo.
    exit /b 1
)

echo Ollama is installed. Checking models...
echo.

REM Check if llama3 is installed
ollama list | findstr "llama3" >nul 2>&1
if %errorlevel% neq 0 (
    echo Pulling llama3 model (this may take a while)...
    ollama pull llama3
) else (
    echo llama3 model is already installed.
)

REM Check if nomic-embed-text is installed
ollama list | findstr "nomic-embed-text" >nul 2>&1
if %errorlevel% neq 0 (
    echo Pulling nomic-embed-text model...
    ollama pull nomic-embed-text
) else (
    echo nomic-embed-text model is already installed.
)

echo.
echo ========================================
echo Ollama setup complete!
echo ========================================
echo.
echo To start Ollama server, run: ollama serve
echo.

REM List all installed models
echo Installed models:
ollama list
