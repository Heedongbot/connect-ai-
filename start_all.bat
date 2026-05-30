@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ================================================
echo   NutriStack Lab v5 - AI Autonomous System
echo   [Autonomous Driving Mode ACTIVE]
echo ================================================
echo.

echo [1/2] Starting Scheduler (+ Watchdog)...
start "Scheduler" cmd /k "python daily_scheduler_v5.py"

timeout /t 3 /nobreak > nul

echo [2/2] Starting Hernex Telegram Bot...
start "Hernex_Telegram" cmd /k "python hernex_agent.py"

timeout /t 2 /nobreak > nul

echo.
echo ================================================
echo   All 2 systems launched!
echo   Scheduler    : topic_bank.json 스케줄 + 오케스트레이터 워치독
echo   Telegram Bot : Hernex Agent (알림/제어)
echo   Orchestrator : 스케줄러가 백그라운드로 자동 시작/재시작 관리
echo ================================================
echo.
echo   [Task Scheduler - 자동 배치]
echo   02:00 CriticB_Audit  - Critic B 감사 + 캘리브레이션
echo   04:00 SelfHeal       - 자가 치유
echo   07:00 MorningReport  - 모닝 리포트
echo ================================================
echo.
pause
