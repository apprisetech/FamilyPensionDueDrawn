import sys
if '--self-test' in sys.argv:
    import tkinter as tk
    from rapidocr_onnxruntime import RapidOCR
    from playwright.sync_api import sync_playwright
    from openpyxl import Workbook
    import fitz,numpy,lxml.etree
    root=tk.Tk();root.withdraw();root.update();root.destroy()
    RapidOCR()
    with sync_playwright() as p:
        from pathlib import Path
        browser=next((Path(sys._MEIPASS)/'browser').rglob('chrome.exe'))
        b=p.chromium.launch(executable_path=str(browser),headless=True)
        page=b.new_page();page.set_content('<title>Ready</title>');assert page.title()=='Ready';b.close()
    print('Portable self-test passed: GUI, OCR models, Excel, PDF and browser.')
else:
    from pension_tool.desktop import main
    if __name__=='__main__':main()
