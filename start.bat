@echo off
title TripMate-AI Server
echo ========================================
echo   TripMate-AI - Starting Server...
echo ========================================
echo.
cd /d "%~dp0"
python app.py
pause

