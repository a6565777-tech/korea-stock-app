@echo off
chcp 65001 >nul
REM Briefing launcher. First arg = slot: overnight/morning/midday/afternoon/closing
REM Default: morning

cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

set SLOT=%1
if "%SLOT%"=="" set SLOT=morning

python -m src.analyzers.briefing %SLOT%

exit /b %errorlevel%
