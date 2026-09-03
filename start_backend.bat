@echo off
setlocal
title FraudShield Backend Launcher
cd /d "%~dp0"

echo ================================================================
echo           FraudShield Backend API Service
echo ================================================================
echo.

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" run_server.py
) else (
    python run_server.py
)

pause
