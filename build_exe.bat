@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    call setup.bat
)

echo Installing PyInstaller...
".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 goto :fail

echo Building...
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --windowed --name Yinglu ^
  --icon assets\icon.ico ^
  --add-data "assets;assets" ^
  --collect-all imageio_ffmpeg ^
  --collect-all soundcard ^
  --collect-all dxcam ^
  --collect-all comtypes ^
  --hidden-import mss.windows ^
  --hidden-import win32gui --hidden-import win32ui --hidden-import win32api ^
  run.pyw
if errorlevel 1 goto :fail

echo.
echo Done: dist\Yinglu\Yinglu.exe
pause
exit /b 0

:fail
echo.
echo [ERROR] Build failed.
pause
exit /b 1
