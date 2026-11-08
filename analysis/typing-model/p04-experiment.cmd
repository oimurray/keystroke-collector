@echo off
setlocal
cd /d "%~dp0"
set "KS_DATA=%~1"
if not defined KS_DATA set "KS_DATA=%~dp0..\.."
python p04_experiment.py --data "%KS_DATA%"
if errorlevel 1 (
  echo Experiment failed. Check the message above.
  pause
  exit /b 1
)
echo Open the summary.md path printed above. Each run preserves earlier reports.
pause
