@echo off
chcp 65001 >nul
REM Realtime monitor launcher. Auto-exits at market close.
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

python -m src.analyzers.realtime

exit /b %errorlevel%
