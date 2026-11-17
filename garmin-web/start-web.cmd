@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto run
if exist "..\.garmin-venv\Scripts\python.exe" (
  "..\.garmin-venv\Scripts\python.exe" server.py
  pause
  exit /b
)
py -3.12 -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
:run
".venv\Scripts\python.exe" server.py
:failed
pause
