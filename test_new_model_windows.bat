@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\preview\start-model-test.ps1" %*
if errorlevel 1 pause
