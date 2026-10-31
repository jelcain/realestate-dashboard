@echo off
cd /d "%~dp0"
title 부동산 정보 조회 시스템 점검

if exist ".venv\Scripts\python.exe" goto run
echo 먼저 '대시보드 실행.bat'을 한 번 실행해 프로그램을 설치하세요.
goto end

:run
echo 점검 중입니다. 30초 정도 걸립니다...
".venv\Scripts\python" scripts\check_health.py

:end
echo.
pause
