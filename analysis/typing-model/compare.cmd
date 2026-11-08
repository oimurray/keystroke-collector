@echo off
setlocal
cd /d "%~dp0"
set "KS_DATA=%~1"
if not defined KS_DATA set "KS_DATA=%~dp0..\.."
set "KS_PYTHON=python"
if exist ".venv-comparison\Scripts\python.exe" set "KS_PYTHON=.venv-comparison\Scripts\python.exe"
"%KS_PYTHON%" compare_models.py --data "%KS_DATA%"
if errorlevel 1 (
  echo Comparison failed. Check the error above and the README setup instructions.
  pause
  exit /b 1
)
echo Open reports\model_comparison.md to review the results.
pause
