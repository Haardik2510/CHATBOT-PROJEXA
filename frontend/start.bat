@echo off
echo ========================================
echo SET Academic Chatbot Frontend
echo ========================================
echo.

REM Check if node_modules exists
if not exist "node_modules" (
    echo Installing dependencies...
    call npm install
    echo.
)

echo Starting React development server...
echo The app will open at http://localhost:3000
echo.

call npm start
