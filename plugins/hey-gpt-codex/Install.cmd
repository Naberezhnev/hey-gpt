@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install.ps1"
if errorlevel 1 (
  echo Installation failed. Read the message above.
) else (
  echo Restart Codex, review the plugin hooks, then enable Hey GPT in your task.
)
pause
