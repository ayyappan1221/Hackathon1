@echo off
setlocal enabledelayedexpansion
title EleGuard AI - One Click Starter
color 0A

:: =========================================================
:: EleGuard AI - start.bat
:: One-click launcher for Hackathon demo
:: Starts: Backend (FastAPI) -> AI (YOLO) -> IoT (simulator) -> Frontend (Vite)
:: Run by double-clicking this file from E:\Hackathon\
:: =========================================================

echo.
echo  =================================================
echo   🐘 EleGuard AI v2.0 - Starting...
echo  =================================================
echo.

:: Get script directory (handles spaces)
set "ROOT=%~dp0"
:: Remove trailing slash
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

echo [INFO] Project root: %ROOT%
echo.

:: ---- Check Python ----
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH. Install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)
echo [OK] Python found
python --version

:: ---- Check Node ----
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found in PATH. Install Node 18+.
    pause
    exit /b 1
)
echo [OK] Node found
node --version
echo.

:: ---- Optional: Install dependencies if missing (uncomment if needed) ----
:: echo [INFO] Checking Python deps...
:: python -m pip install --upgrade pip
:: python -m pip install fastapi "uvicorn[standard]" python-multipart ultralytics opencv-python requests
:: echo [INFO] Checking Frontend deps...
:: if not exist "%ROOT%\frontend\node_modules" (
::     echo [INFO] Installing frontend deps...
::     pushd "%ROOT%\frontend"
::     call npm install
::     popd
:: )

:: ---- Check frontend node_modules ----
if not exist "%ROOT%\frontend\node_modules" (
    echo [WARN] frontend\node_modules missing. Running npm install...
    pushd "%ROOT%\frontend"
    call npm install
    if errorlevel 1 (
        echo [ERROR] npm install failed
        pause
        exit /b 1
    )
    popd
    echo [OK] Frontend deps installed
)

echo.
echo [1/4] Starting Backend  (FastAPI :8000) ...
:: --reload for dev, remove --reload for stable demo
start "EleGuard - Backend :8000" cmd /k "cd /d "%ROOT%\backend" && echo [Backend] http://127.0.0.1:8000 ^& docs http://127.0.0.1:8000/docs && python -m uvicorn main:app --reload --port 8000"

:: Give backend time to bind before AI/IoT try to POST
echo [INFO] Waiting 4s for backend to boot...
timeout /t 4 /nobreak >nul

echo [2/4] Starting AI Detection  (YOLO11n - video/webcam) ...
start "EleGuard - AI Detection" cmd /k "cd /d "%ROOT%\ai" && echo [AI] YOLO tracking started - switch VIDEO/CAMERA from dashboard && python detect_and_send.py"

timeout /t 2 /nobreak >nul

echo [3/4] Starting IoT Simulator  (NODE_01) ...
start "EleGuard - IoT Simulator" cmd /k "cd /d "%ROOT%\iot" && echo [IoT] NODE_01 telemetry every 2s && python simulator.py"

timeout /t 2 /nobreak >nul

echo [4/4] Starting Frontend  (Vite :5173) ...
start "EleGuard - Frontend :5173" cmd /k "cd /d "%ROOT%\frontend" && echo [Frontend] http://localhost:5173 && npm run dev"

echo.
echo  =================================================
echo   ✅ All services launched in separate windows!
echo  =================================================
echo   Backend  : http://127.0.0.1:8000        ^(docs /docs^)
echo   Frontend : http://localhost:5173
echo   VideoFeed: http://127.0.0.1:8000/api/video-feed
echo  =================================================
echo   Start order: Backend -^> AI -^> IoT -^> Frontend
echo   To stop: close each window or run stop.bat / Ctrl+C
echo  =================================================
echo.
echo [TIP] If backend restarts, AI/IoT will auto-retry. Check each window for logs.
echo.
pause
endlocal
