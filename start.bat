@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo First run: setting up environment...
    call setup.bat
)

if not exist ".venv\Scripts\pythonw.exe" (
    echo [ERROR] Setup incomplete.
    pause
    exit /b 1
)

start "Yinglu" ".venv\Scripts\pythonw.exe" "run.pyw"
