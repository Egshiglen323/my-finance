@echo off
cd /d %~dp0
echo === My Finance setup ===
where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" in the installer, then run setup.bat again.
  pause
  exit /b 1
)
if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv
)
call .venv\Scripts\activate
echo Installing packages (first time takes a few minutes)...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt
if errorlevel 1 (
  echo Package install failed. Check your internet connection and run setup.bat again.
  pause
  exit /b 1
)
python setup_db.py
if errorlevel 1 (
  pause
  exit /b 1
)
echo.
echo Done! Double-click run.bat to start the app.
pause
