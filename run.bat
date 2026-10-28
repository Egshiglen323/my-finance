@echo off
cd /d %~dp0
if not exist .venv (
  echo Run setup.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate
start "" cmd /c "timeout /t 4 >nul & start http://localhost:8501"
echo My Finance is running at http://localhost:8501  -  close this window to stop it.
streamlit run app.py
pause
