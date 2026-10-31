@echo off
cd /d "%~dp0"
title 부동산 대시보드

if exist ".venv\Scripts\python.exe" goto check_env
echo [처음 실행] 프로그램을 설치합니다. 몇 분 걸립니다...
python -m venv .venv
if errorlevel 1 goto no_python
".venv\Scripts\python" -m pip install -r requirements.txt
if errorlevel 1 goto fail

:check_env
if exist ".env" goto check_running
copy ".env.example" ".env" >nul
echo [안내] .env 파일을 만들었습니다. 메모장으로 열어 공공데이터포털 키를 입력하세요.

:check_running
curl -s -o nul http://localhost:8501/_stcore/health
if errorlevel 1 goto start_server
echo 대시보드가 이미 실행 중입니다. 브라우저를 엽니다.
start "" http://localhost:8501
exit /b 0

:start_server
echo 대시보드를 시작합니다: http://localhost:8501
echo 이 창을 닫으면 대시보드가 꺼집니다. 진행 중인 수집은 계속됩니다.
start "" /b cmd /c "timeout /t 5 >nul & start "" http://localhost:8501"
".venv\Scripts\python" -m streamlit run app.py --server.port 8501 --server.address localhost --server.headless true --browser.gatherUsageStats false
goto end

:no_python
echo Python이 설치되어 있지 않습니다. python.org 에서 Python 3.11 이상을 설치하세요.
goto end

:fail
echo 설치에 실패했습니다. 위 오류 메시지를 확인하세요.

:end
pause
