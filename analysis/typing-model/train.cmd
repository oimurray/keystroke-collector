@echo off
setlocal
cd /d "%~dp0"
set "KS_DATA=%~1"
if defined KS_DATA goto train
for %%D in ("%~dp0" "%~dp0.." "%~dp0..\.." "%~dp0..\keystroke-collector" "C:\Vs_repos\keystroke-collector") do (
  if not defined KS_DATA if exist "%%~fD\manifest.json" if exist "%%~fD\data\" set "KS_DATA=%%~fD"
)
if not defined KS_DATA (
  echo Collector folder not found. Run train.cmd "C:\path\to\keystroke-collector"
  pause
  exit /b 1
)
:train
python keystroke_model.py train --data "%KS_DATA%"
if errorlevel 1 (
  echo Training failed. Check the message above.
  pause
  exit /b 1
)
python keystroke_model.py train --data "%KS_DATA%" --method knn --k 5
if errorlevel 1 (
  echo kNN training failed. Check the message above.
  pause
  exit /b 1
)
echo Both models trained. Run start.cmd to use them.
pause
