@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  ".venv\Scripts\python.exe" -c "import webview, pymupdf, rapidocr_onnxruntime, playwright.sync_api" >nul 2>&1
  if errorlevel 1 ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto failed
  start "" ".venv\Scripts\pythonw.exe" app.py
  exit /b
)
if exist "Test Exchange Converter.exe" (
  powershell -NoProfile -Command "try { Start-Process -FilePath '.\Test Exchange Converter.exe' -ErrorAction Stop; exit 0 } catch { Write-Host 'Windows blocked the packaged app. Trying the Python source launcher.'; exit 1 }"
  if not errorlevel 1 exit /b
)
if not exist ".venv\Scripts\pythonw.exe" (
  echo First-time setup: installing the local runtime dependencies.
  py -3 -m venv .venv
  if errorlevel 1 goto failed
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto failed
)
start "" ".venv\Scripts\pythonw.exe" app.py
exit /b
:failed
echo Setup failed. Install Python 3.11 or newer from python.org, then try again.
pause
