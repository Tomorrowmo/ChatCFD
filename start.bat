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

:: Wait until post_service actually accepts connections.
:: A fixed sleep is unreliable — loading VTK can take 10-20s, and if the agent
:: starts first its MCP pool fails with "post_service: failed".
echo      Waiting for PostService to accept connections...
:waitpost
timeout /t 2 /nobreak >nul
powershell -NoProfile -Command "try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',8001);$c.Close();exit 0}catch{exit 1}"
if errorlevel 1 goto waitpost
echo      PostService is up.

:: Start agent (port 8090)
echo [2/3] Starting Agent Service (port 8090)...
start "ChatCFD - Agent" cmd /k "cd /d %~dp0 && %PYTHON% -m uvicorn agent.main:app --host 0.0.0.0 --port 8090 --reload"

:: Start web frontend (vite dev)
echo [3/3] Starting Web Frontend...
start "ChatCFD - Web" cmd /k "cd /d %~dp0web && npm run dev"

echo.
echo ========================================
echo   All services started!
echo   PostService : http://localhost:8001
echo   Agent       : http://localhost:8090
echo   Web         : http://localhost:5173
echo ========================================
echo.
echo Close this window or press any key to exit.
pause >nul
