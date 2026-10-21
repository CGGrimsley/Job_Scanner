@echo off
title Job Scanner
cd /d "%~dp0"
if not exist .env copy .env.example .env >nul
where py >nul 2>nul && (py -3 -m job_scanner serve --open) || (python -m job_scanner serve --open)
pause
