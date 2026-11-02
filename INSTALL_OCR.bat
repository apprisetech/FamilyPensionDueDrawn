@echo off
cd /d "%~dp0"
if not exist .venv312\Scripts\python.exe (
 echo Run the updated INSTALL.bat first. Python 3.12 is required.
 pause
 exit /b 1
)
.venv312\Scripts\python.exe -c "import sys; assert sys.version_info[:2]==(3,12), 'Python 3.12 required'"
if errorlevel 1 exit /b 1
.venv312\Scripts\python.exe -m pip install -r requirements-ocr.txt
if errorlevel 1 goto failed
.venv312\Scripts\python.exe -c "from rapidocr_onnxruntime import RapidOCR; RapidOCR(); print('OCR ready')"
if errorlevel 1 goto failed
pause
exit /b 0
:failed
echo OCR setup failed. Keep this error message for troubleshooting.
pause
exit /b 1
