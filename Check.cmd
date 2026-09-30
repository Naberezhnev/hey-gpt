@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run Run.cmd once to prepare Python and dependencies.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m hey_gpt.diagnostics --microphone
set "check_result=%errorlevel%"
pause
exit /b %check_result%
