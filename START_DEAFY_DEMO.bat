@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0scripts\start-deafy-demo.ps1" %*
set "DEAFY_EXIT=%ERRORLEVEL%"
if not "%DEAFY_EXIT%"=="0" if /i not "%~1"=="-Check" pause
exit /b %DEAFY_EXIT%
