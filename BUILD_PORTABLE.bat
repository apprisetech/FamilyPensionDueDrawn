@echo off
cd /d "%~dp0"
py -3.12 build_windows.py
if errorlevel 1 (
 echo Build failed. This is a developer build step, not an end-user installation.
) else (
 echo Share FamilyPensionTool_Windows_Portable.zip with colleagues.
)
pause
