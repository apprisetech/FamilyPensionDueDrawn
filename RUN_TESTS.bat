@echo off
cd /d "%~dp0"
.venv312\Scripts\python.exe -m unittest discover -s tests -v
pause
