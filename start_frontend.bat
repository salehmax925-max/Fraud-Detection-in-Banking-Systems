@echo off
setlocal
title FraudShield Frontend Launcher
cd /d "%~dp0frontend"

echo ================================================================
echo           FraudShield Frontend Dashboard (React + Vite)
echo ================================================================
echo.

npm run dev
pause
