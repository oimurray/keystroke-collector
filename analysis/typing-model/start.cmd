@echo off
setlocal
cd /d "%~dp0"
if not exist "models\baseline.json" (
  echo No model found. Run train.cmd first.
  pause
  exit /b 1
)
echo Open http://127.0.0.1:8765 in your browser after the server is ready.
python keystroke_model.py serve
if errorlevel 1 pause
