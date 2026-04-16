@echo off
REM 실시간 모니터 런처. 장 마감 시 자동 종료됨.
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

python -m src.analyzers.realtime

exit /b %errorlevel%
