@echo off
setlocal
cd /d "%~dp0"
set "KS_DATA=%~1"
if not defined KS_DATA set "KS_DATA=%~dp0..\.."
python identity_model.py train --data "%KS_DATA%"
if errorlevel 1 (
  echo Training failed. Check the message above.
  pause
  exit /b 1
)
echo Open http://127.0.0.1:8768 in your browser. Keep this terminal open.
python identity_model.py serve --port 8768
if errorlevel 1 pause
