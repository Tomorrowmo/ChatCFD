@echo off
chcp 65001 >nul
title ChatCFD Dev Server

echo [ChatCFD] Activating conda environment...
call conda activate PostProcessTool

echo [ChatCFD] Starting Post Service (port 8000)...
start "PostService" cmd /k "conda activate PostProcessTool && cd /d %~dp0 && python -m post_service.server"

echo [ChatCFD] Starting Agent Service (port 8080)...
timeout /t 2 /nobreak >nul
start "Agent" cmd /k "conda activate PostProcessTool && cd /d %~dp0 && python -m agent.main"

echo [ChatCFD] Starting Frontend (port 5173)...
timeout /t 2 /nobreak >nul
start "Frontend" cmd /k "cd /d %~dp0web && npx vite --host"

echo.
echo [ChatCFD] All services starting:
echo   Post Service:  http://localhost:8000
echo   Agent:         http://localhost:8080
echo   Frontend:      http://localhost:5173
echo.
echo Close this window won't stop services. Close each service window to stop them.
echo pause
