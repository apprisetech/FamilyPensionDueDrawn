"""Run ON WINDOWS to produce a complete portable application folder."""
from pathlib import Path
import os,sys,subprocess,shutil

def run(*args,env=None):subprocess.run(list(args),check=True,env=env)
def main():
    if sys.platform!='win32':raise SystemExit('A Windows build runner is required. Linux cannot produce this Windows executable.')
    if sys.version_info[:2]!=(3,12):raise SystemExit('The builder requires Python 3.12, 64-bit. End users need no Python.')
    import struct
    if struct.calcsize('P')!=8:raise SystemExit('64-bit builder required.')
    root=Path(__file__).resolve().parent;os.chdir(root)
    run(sys.executable,'-m','pip','install','-r','requirements.txt','-r','requirements-ocr.txt','pyinstaller>=6.11,<7')
    run(sys.executable,'-m','unittest','discover','-s','tests','-v')
    browsers=root/'build_browsers';env=os.environ.copy();env['PLAYWRIGHT_BROWSERS_PATH']=str(browsers)
    run(sys.executable,'-m','playwright','install','chromium',env=env)
    args=[sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--name','FamilyPensionTool','--add-data',str(browsers)+';browser']
    for package in ['rapidocr_onnxruntime','onnxruntime','playwright','fitz','pymupdf','numpy','cv2','openpyxl','lxml']:
        args+=['--collect-all',package]
    args+=['--hidden-import','tkinter','--hidden-import','tkinter.ttk','app.py']
    run(*args)
    dist=root/'dist'/'FamilyPensionTool'
    run(str(dist/'FamilyPensionTool.exe'),'--self-test')
    (dist/'READ_ME.txt').write_text('Extract the entire ZIP. Double-click FamilyPensionTool.exe. No Python or pip setup is needed. Keep _internal beside the EXE. SAMPANN requires internet and your own login/OTP. Select your updated DR_Master.xlsx.\n',encoding='utf-8')
    shutil.copy2(root/'PORTABLE_USER_GUIDE.md',dist/'USER_GUIDE.md')
    zipfile=shutil.make_archive(str(root/'FamilyPensionTool_Windows_Portable'),'zip',dist)
    print('Built and smoke-tested:',zipfile)
if __name__=='__main__':main()
