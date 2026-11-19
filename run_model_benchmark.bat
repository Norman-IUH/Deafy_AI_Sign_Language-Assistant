@echo off
if not exist "%~dp0.venv-model-test\Scripts\python.exe" (
  echo Run test_new_model_windows.bat first to prepare the isolated test environment.
  pause
  exit /b 1
)
"%~dp0.venv-model-test\Scripts\python.exe" "%~dp0benchmark_models.py" %*
if errorlevel 1 (
  pause
  exit /b 1
)
echo Report: %~dp0.tools\model-benchmark\latest\report.md
