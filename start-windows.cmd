@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" || (echo Python 3.11 or newer is required. & pause & exit /b 1)
  py -3 -m venv .venv || (echo Failed to create virtual environment. & pause & exit /b 1)
)
.venv\Scripts\python.exe -c "import flask, waitress, filelock" 2>nul || (
  .venv\Scripts\python.exe -m pip install -r requirements.txt || (echo Dependency installation failed. & pause & exit /b 1)
)
echo Open http://127.0.0.1:8765 in your browser.
echo Keep this window open while using ClipForge Delivery.
.venv\Scripts\python.exe app.py
if errorlevel 1 pause
endlocal
