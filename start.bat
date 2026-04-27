@echo off
chcp 65001 >nul
title ChatCFD Launcher

echo ========================================
echo   ChatCFD - Starting All Services
echo ========================================
echo.

:: Use conda env's Python directly to avoid slow conda activate in each window
set PYTHON=D:\TOOL\Conda\conda\envs\PostProcessTool\python.exe

:: Start post_service on port 8001 to avoid conflict with SimGraph on 8000
echo [1/3] Starting Post Service (port 8001)...
start "ChatCFD - PostService" cmd /k "cd /d %~dp0 && %PYTHON% -m uvicorn post_service.server:app --host 0.0.0.0 --port 8001 --reload"

:: Wait for post_service to be ready (check health endpoint)
echo      Waiting for PostService...
timeout /t 5 /nobreak >nul

:: Start agent (port 8080)
echo [2/3] Starting Agent Service (port 8080)...
start "ChatCFD - Agent" cmd /k "cd /d %~dp0 && %PYTHON% -m uvicorn agent.main:app --host 0.0.0.0 --port 8080 --reload"

:: Start web frontend (vite dev)
echo [3/3] Starting Web Frontend...
start "ChatCFD - Web" cmd /k "cd /d %~dp0web && npm run dev"

echo.
echo ========================================
echo   All services started!
echo   PostService : http://localhost:8001
echo   Agent       : http://localhost:8080
echo   Web         : http://localhost:5173
echo ========================================
echo.
echo Close this window or press any key to exit.
pause >nul
