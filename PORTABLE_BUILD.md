# Portable Windows build

This package contains BUILD INSTRUCTIONS AND SOURCE, not a compiled EXE.

Build once on Windows with Python 3.12 (64-bit), using BUILD_PORTABLE.bat.
Alternatively place this project's contents at the root of a GitHub repository,
including .github/workflows/windows-portable.yml, then manually run the Build
Windows Portable workflow. Download its resulting artifact after success.

The build includes Python, Tcl/Tk, PDF/Excel libraries, OCR libraries and model
files, Playwright driver and Chromium. It tests OCR initialization, the GUI,
and the bundled browser before producing FamilyPensionTool_Windows_Portable.zip.
Recipients extract that finished ZIP and run FamilyPensionTool.exe.
The entire folder, including _internal, must remain together.

Dependencies and browser are downloaded on the BUILD machine only. Running
SAMPANN still requires internet and manual login/OTP. No case data, sessions,
DR_Master or bank information is included in the shareable build.

This build has not yet been executed on a Windows runner in this session.
Calculation tests are separate from live SAMPANN verification.
