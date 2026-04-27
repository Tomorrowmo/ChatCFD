@echo off
chcp 65001 >nul
title ChatCFD - Run All Tests

set PYTHON=D:\TOOL\Conda\conda\envs\PostProcessTool\python.exe

echo ======================================================================
echo [1/3] Unit tests (pytest)
echo ======================================================================
%PYTHON% -m pytest tests/ -q
if errorlevel 1 (
    echo.
    echo [FAIL] Unit tests failed
    pause
    exit /b 1
)

echo.
echo ======================================================================
echo [2/3] Backend integration tests
echo ======================================================================
%PYTHON% -X utf8 -m tools.integration_test
if errorlevel 1 (
    echo.
    echo [FAIL] Integration tests failed
    pause
    exit /b 1
)

echo.
echo ======================================================================
echo [3/3] LLM behavior tests (requires PostService running on 8001)
echo ======================================================================
%PYTHON% -X utf8 -m tools.llm_behavior_test --quick
if errorlevel 1 (
    echo.
    echo [FAIL] LLM tests failed
    pause
    exit /b 1
)

echo.
echo ======================================================================
echo  ALL TESTS PASSED
echo ======================================================================
pause
