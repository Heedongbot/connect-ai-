@echo off
chcp 65001 > nul
title NutriStack 로그 뷰어
cd /d "%~dp0"
echo =============================================
echo   NutriStack 실시간 로그 (Ctrl+C 로 종료)
echo =============================================
echo.
powershell -Command "Get-Content orchestrator.log -Wait -Tail 30 -Encoding UTF8"
