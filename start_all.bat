@echo off
setlocal
title FraudShield Full System Launcher
cd /d "%~dp0"

echo ================================================================
echo           FraudShield - Banking Fraud Detection System
echo           AI-Powered Security Platform
echo ================================================================
echo.

:: Detect Python (.venv or system)
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_EXE=%~dp0.venv\Scripts\python.exe"
) else (
    set "PY_EXE=python"
)

echo [1/3] Launching Backend API (FastAPI + PostgreSQL + Ollama + PandasAI)...
start "FraudShield Backend" /d "%~dp0" "%PY_EXE%" run_server.py

echo [2/3] Launching Frontend Dashboard (React + Vite)...
start "FraudShield Frontend" /d "%~dp0frontend" cmd /k "npm run dev"

echo.
echo [3/3] Initializing services and opening web dashboard...
timeout /t 3 /nobreak >nul

start http://localhost:5173

echo.
echo ================================================================
echo   [READY] FraudShield is running!
echo   --------------------------------------------------------------
echo   * Web Dashboard: http://localhost:5173
echo   * Backend API:   http://localhost:8000/docs
echo   * AI Model:      Ollama qwen3:8b + PandasAI Data Intelligence
echo   * Database:      PostgreSQL (127.0.0.1:5432)
echo.
echo   * Login Accounts (Password: 2004):
echo     - saleh    (Admin)
echo     - amin     (Admin)
echo     - user1    (User / Analyst)
echo     - hussain  (CEO)
echo ================================================================
echo.
pause
