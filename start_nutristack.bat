@echo off
title NutriStack Lab v5.0

echo ============================================
echo  NutriStack Lab v5.0
echo  Human Entropy Layer ACTIVE
echo  11 Archetypes / 4~8 Sections / 1200~4000w
echo ============================================
echo.

cd /d "%~dp0"

echo [1/2] Starting Orchestrator v5...
start "Orchestrator v5.0" cmd /k "python 00_NutriStack_Grand_Orchestrator_v5.py"
timeout /t 3 /nobreak >nul

echo [2/2] Starting Scheduler v5...
start "Scheduler v5.0" cmd /k "python daily_scheduler_v5.py"
timeout /t 3 /nobreak >nul

echo.
echo ============================================
echo  Running! Test: python daily_scheduler_v5.py test
echo ============================================
pause