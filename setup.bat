@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.9+ and add it to PATH.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv --system-site-packages .venv
    if errorlevel 1 goto :fail
)

echo Installing dependencies (first run may take a few minutes)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo Done. Double-click start.bat to launch Yinglu.
pause
exit /b 0

:fail
echo.
echo [ERROR] Setup failed. Check your network / Python installation.
pause
exit /b 1
