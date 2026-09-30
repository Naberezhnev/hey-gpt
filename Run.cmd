@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.12 64-bit with Tkinter and Python Launcher from python.org.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -c "import uiautomation, vosk, sounddevice, tkinter" >nul 2>nul
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto failed
)
start "Hey GPT" ".venv\Scripts\pythonw.exe" -m hey_gpt.app
if errorlevel 1 goto failed
exit /b 0
:failed
echo Setup or startup failed. See the message above.
pause
exit /b 1
