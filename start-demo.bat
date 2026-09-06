@echo off
REM GoldenHour AI - one-click demo launcher (double-click this file)
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python launcher 'py' not found. Install Python 3.10+ from python.org
  echo and re-run this file.
  pause
  exit /b 1
)

echo [1/3] Seeding Chennai demo data...
py scripts\demo.py
if errorlevel 1 (
  echo [ERROR] Demo seeding failed. Did you run: py -m pip install -r backend\requirements.txt ?
  pause
  exit /b 1
)

echo [2/3] Starting backend on http://localhost:8000 ...
start "GoldenHour AI - backend (keep this window open)" /min py -m uvicorn backend.app.main:app --port 8000

echo Waiting for backend to respond...
for /L %%i in (1,1,30) do (
  py -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=2)" >nul 2>nul
  if not errorlevel 1 goto :healthy
  timeout /t 2 /nobreak >nul
)
echo [ERROR] Backend did not respond after ~60s.
echo Check the "GoldenHour AI - backend" window for errors, or run manually:
echo   py -m uvicorn backend.app.main:app --port 8000
pause
exit /b 1

:healthy
echo [3/3] Backend is up. Opening dashboard...
start "" "http://localhost:8000/"
echo.
echo Dashboard: http://localhost:8000/   (API docs: http://localhost:8000/docs)
echo Keep the backend window open while using the demo.
pause
