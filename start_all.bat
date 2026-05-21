@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ================================================
echo   NutriStack Lab v5.4 - AI Autonomous System
echo   [Autonomous Driving Mode ACTIVE]
echo ================================================
echo.

echo [1/5] Starting Orchestrator...
start "Orchestrator" cmd /k "python 00_NutriStack_Grand_Orchestrator_v5.py"

timeout /t 3 /nobreak > nul

echo [2/5] Starting Scheduler...
start "Scheduler" cmd /k "python daily_scheduler_v5.py"

timeout /t 3 /nobreak > nul

echo [3/5] Starting Discord Bot...
start "Discord_Bot" cmd /k "python bot_start.py"

timeout /t 3 /nobreak > nul

echo [4/5] Starting Hernex Telegram Bot...
start "Hernex_Telegram" cmd /k "python hernex_agent.py"

timeout /t 3 /nobreak > nul

echo [5/5] Starting Autonomous CEO (Audit + In-Place Rewrite)...
start "CEO" cmd /k "python 00_NutriStack_Autonomous_CEO_v1.py"

timeout /t 2 /nobreak > nul

echo.
echo ================================================
echo   All 5 systems launched!
echo   Telegram Bot: Active (Hernex Agent)
echo   Autonomous CEO: Active (Quality Audit & Healing)
echo ================================================
echo.
pause
