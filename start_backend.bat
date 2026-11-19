@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\preview\start-preview.ps1" -Target backend
if errorlevel 1 (
  pause
  exit /b 1
)
exit /b 0
