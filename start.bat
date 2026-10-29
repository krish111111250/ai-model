@echo off
rem Start Krish AI on Windows: Ollama, MongoDB, engine, local gateway, frontend.
rem
rem   start.bat         production: the engine serves the built frontend
rem                     (frontend\dist, made by install.bat) on port 8000
rem   start.bat --dev   development: Vite on port 5173, with hot reload
rem
rem Each service runs in its own minimized window titled "Krish AI ...", with
rem its output in logs\. Close those windows to stop it, or run:
rem   taskkill /fi "WINDOWTITLE eq Krish AI*" /t /f

setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "ROOT=%CD%"
set "LOGS=%ROOT%\logs"
set "PY=%ROOT%\backend\venv\Scripts\python.exe"

set "DEV=0"
if /i "%~1"=="--dev" set "DEV=1"

if not exist "%PY%" (
  echo [ERROR] No Python environment in backend\venv. Run install.bat first.
  exit /b 1
)

if not exist "%LOGS%" mkdir "%LOGS%"

rem Same model settings as start.sh: keep the model loaded between questions
rem but not all day, and one request at a time.
if not defined OLLAMA_KEEP_ALIVE set "OLLAMA_KEEP_ALIVE=5m"
if not defined OLLAMA_NUM_PARALLEL set "OLLAMA_NUM_PARALLEL=1"

echo Starting Krish AI

echo 1/5 Ollama
curl -s -o nul http://localhost:11434
if errorlevel 1 (
  start "Krish AI Ollama" /min cmd /c "ollama serve >> "%LOGS%\ollama.log" 2>&1"
  call :wait_for http://localhost:11434 Ollama
) else (
  echo    already running
)

echo 2/5 MongoDB
rem MongoDB answers plain HTTP on its port with a short notice, which is
rem enough to tell it is up. On Windows it usually runs as a service.
curl -s -o nul http://localhost:27017
if errorlevel 1 (
  where mongod >nul 2>&1
  if errorlevel 1 (
    echo    [WARN] MongoDB is not running and mongod is not on PATH.
    echo           Start the MongoDB service, then run start.bat again.
  ) else (
    if not exist "%USERPROFILE%\mongodb-data" mkdir "%USERPROFILE%\mongodb-data"
    start "Krish AI MongoDB" /min cmd /c "mongod --dbpath "%USERPROFILE%\mongodb-data" >> "%LOGS%\mongod.log" 2>&1"
    call :wait_for http://localhost:27017 MongoDB
  )
) else (
  echo    already running
)

echo 3/5 Engine (FastAPI)
curl -s -o nul http://localhost:8000/health
if errorlevel 1 (
  start "Krish AI Engine" /min /d "%ROOT%\backend" cmd /c ""%PY%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 >> "%LOGS%\backend.log" 2>&1"
  call :wait_for http://localhost:8000/health Engine
) else (
  echo    already running
)

echo 4/5 Local gateway (port 8001)
curl -s -o nul http://localhost:8001
if errorlevel 1 (
  rem The gateway reads no .env of its own, so its KRISH_* settings are
  rem handed over here. A value already set in this shell wins.
  for /f "usebackq eol=# tokens=1,* delims==" %%a in (`findstr /r /b "KRISH_[A-Z_]*=" "%ROOT%\backend\.env"`) do (
    if not defined %%a if not "%%b"=="" set "%%a=%%b"
  )
  start "Krish AI Gateway" /min /d "%ROOT%" cmd /c ""%PY%" "%ROOT%\client_gateway.py" >> "%LOGS%\gateway.log" 2>&1"
  call :wait_for http://localhost:8001 Gateway
) else (
  echo    already running
)

set "APP_URL=http://localhost:8000"
if "%DEV%"=="0" if exist "%ROOT%\frontend\dist\index.html" (
  echo 5/5 Frontend - built, served by the engine
  echo    frontend\dist - rebuild with install.bat after changing the UI
  goto :frontend_done
)

echo 5/5 Frontend - Vite dev server
if "%DEV%"=="0" echo    no build in frontend\dist - run install.bat for production
set "APP_URL=http://localhost:5173"
curl -s -o nul http://localhost:5173
if errorlevel 1 (
  start "Krish AI Frontend" /min /d "%ROOT%\frontend" cmd /c "npm run dev >> "%LOGS%\frontend.log" 2>&1"
  call :wait_for http://localhost:5173 Frontend
) else (
  echo    already running
)

:frontend_done

rem Load the model now so the first question is fast.
set "MODEL="
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /b /c:"MAIN_LLM_MODEL=" "%ROOT%\backend\.env"`) do set "MODEL=%%b"
if not defined MODEL set "MODEL=llama3.2:latest"
echo Warming up model: %MODEL%
curl -s -o nul http://localhost:11434/api/generate -d "{\"model\":\"%MODEL%\",\"prompt\":\"hi\",\"stream\":false,\"keep_alive\":\"5m\"}"
if errorlevel 1 (
  echo    [WARN] warm-up failed - check logs\ollama.log
) else (
  echo    model loaded
)

echo.
echo Krish AI is running locally at %APP_URL%
echo    Gateway (your documents): http://localhost:8001
echo    Engine  (answers only):   http://localhost:8000
echo    Logs: %LOGS%
echo    Stop: taskkill /fi "WINDOWTITLE eq Krish AI*" /t /f
exit /b 0

rem Poll a URL until it answers, for up to 60 seconds.
:wait_for
setlocal EnableDelayedExpansion
set /a tries=0
:wait_loop
curl -s -o nul "%~1"
if not errorlevel 1 (
  echo    %~2 ready
  endlocal & exit /b 0
)
set /a tries+=1
if !tries! geq 60 (
  echo    [WARN] %~2 did not come up - check logs\
  endlocal & exit /b 1
)
timeout /t 1 /nobreak >nul
goto wait_loop
