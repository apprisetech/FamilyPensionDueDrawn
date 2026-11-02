@echo off
cd /d "%~dp0"
py -3.12 -c "import sys; assert sys.version_info[:2]==(3,12)" >nul 2>nul
if errorlevel 1 (
 echo Python 3.12 is required. Install the 64-bit Python 3.12 from python.org, then retry.
 pause
 exit /b 1
)
py -3.12 -m venv .venv312
if errorlevel 1 goto failed
.venv312\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Setup complete. Run INSTALL_OCR.bat, then START.bat.
pause
exit /b 0
:failed
echo Setup failed. Read the error above.
pause
exit /b 1
