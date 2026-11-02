@echo off
cd /d "%~dp0"
if not exist .venv312\Scripts\python.exe (
 echo Run INSTALL.bat first.
 pause
 exit /b 1
)
.venv312\Scripts\python.exe app.py
if errorlevel 1 pause
