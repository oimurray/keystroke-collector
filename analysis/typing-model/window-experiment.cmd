@echo off
setlocal
cd /d "%~dp0"
set "KS_DATA=%~1"
if not defined KS_DATA set "KS_DATA=%~dp0..\.."
set "KS_PYTHON=python"
if exist ".venv-comparison\Scripts\python.exe" set "KS_PYTHON=.venv-comparison\Scripts\python.exe"
"%KS_PYTHON%" window_experiment.py --data "%KS_DATA%"
if errorlevel 1 (
  echo Experiment failed. Check the error above and the README setup instructions.
  pause
  exit /b 1
)
echo Each run is saved under reports\window_experiments in its own folder.
pause
