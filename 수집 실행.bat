@echo off
cd /d "%~dp0"
title 부동산 정보 수집

if exist ".venv\Scripts\python.exe" goto run
echo 먼저 '대시보드 실행.bat'을 한 번 실행해 프로그램을 설치하세요.
goto end

:run
echo 관심 단지 전체를 수집합니다: 단지 정보, 실거래, 매물, 뉴스
echo 관심 단지가 많으면 오래 걸립니다. 창을 닫으면 수집이 중단됩니다.
echo.
".venv\Scripts\python" run_daily.py %*

:end
echo.
pause
