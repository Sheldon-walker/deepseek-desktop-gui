@echo off
REM ============================================================
REM  Build DeepSeekDesktop single-file exe
REM  Requires: python (with tkinter, e.g. Anaconda) + pyinstaller
REM  If the Anaconda path below differs on this machine, change LIB.
REM ============================================================

set LIB=D:\ProgramData\anaconda3\Library\bin

call .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name DeepSeekDesktop --icon app.ico --collect-all customtkinter ^
  --add-data "assets\icons;assets\icons" ^
  --add-data "app.ico;." ^
  --add-binary "lib\WebView2Loader.dll;." ^
  --add-binary "%LIB%\tcl86t.dll;." ^
  --add-binary "%LIB%\tk86t.dll;." ^
  --add-binary "%LIB%\ffi.dll;." ^
  --add-binary "%LIB%\libexpat.dll;." ^
  --add-binary "%LIB%\liblzma.dll;." ^
  --add-binary "%LIB%\libbz2.dll;." ^
  --add-binary "%LIB%\libmpdec-4.dll;." ^
  --add-binary "%LIB%\libssl-3-x64.dll;." ^
  --add-binary "%LIB%\libcrypto-3-x64.dll;." ^
  --add-binary "%LIB%\zlib.dll;." ^
  app.py

echo.
echo Done: dist\DeepSeekDesktop.exe
