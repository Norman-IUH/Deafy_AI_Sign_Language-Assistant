@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-preview.ps1" -Target android
if errorlevel 1 (
  pause
  exit /b 1
)
exit /b 0
