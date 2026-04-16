@echo off
REM 브리핑 런처. 첫 인자로 슬롯 받음: morning/midday/afternoon/closing
REM 기본값: morning

cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

set SLOT=%1
if "%SLOT%"=="" set SLOT=morning

python -m src.analyzers.briefing %SLOT%

exit /b %errorlevel%
