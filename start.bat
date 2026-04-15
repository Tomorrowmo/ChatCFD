@echo off
chcp 65001 >nul
title ChatCFD Launcher

echo ========================================
echo   ChatCFD - Starting All Services
echo ========================================
echo.

:: Activate conda environment
call conda activate PostProcessTool

:: Start post_service (port 8000)
echo [1/3] Starting Post Service (port 8000)...
start "ChatCFD - PostService" cmd /k "conda activate PostProcessTool && cd /d %~dp0 && python -m uvicorn post_service.server:app --host 0.0.0.0 --port 8000 --reload"

:: Wait a moment for post_service to initialize
timeout /t 3 /nobreak >nul

:: Start agent (port 8080)
echo [2/3] Starting Agent Service (port 8080)...
start "ChatCFD - Agent" cmd /k "conda activate PostProcessTool && cd /d %~dp0 && python -m uvicorn agent.main:app --host 0.0.0.0 --port 8080 --reload"

:: Start web frontend (vite dev)
echo [3/3] Starting Web Frontend...
start "ChatCFD - Web" cmd /k "cd /d %~dp0web && npm run dev"

echo.
echo ========================================
echo   All services started!
echo   PostService : http://localhost:8000
echo   Agent       : http://localhost:8080
echo   Web         : http://localhost:5173
echo ========================================
echo.
echo Close this window or press any key to exit.
pause >nul
