@echo off
rem Krish AI on-premise installer (Windows).
rem
rem Builds the frontend, creates the Python environment the engine and the
rem local gateway share, and writes backend\.env on first install. Safe to
rem re-run: an existing venv and .env are kept, so it doubles as the upgrade
rem step after a new version is copied in.
rem
rem Downloads npm and pip packages. On an air-gapped machine run it once on a
rem connected machine and copy the whole folder across, or point npm and pip
rem at an internal mirror.

setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "ROOT=%CD%"

echo Starting Krish AI On-Premise Setup...

where npm >nul 2>&1 || (
  echo [ERROR] npm not found. Install Node.js 20+ and re-run.
  exit /b 1
)

rem The py launcher first: "python" on a fresh Windows can be the Microsoft
rem Store stub, which opens the Store instead of running anything.
set "PYTHON="
where py >nul 2>&1 && set "PYTHON=py -3"
if not defined PYTHON (
  where python >nul 2>&1 && set "PYTHON=python"
)
if not defined PYTHON (
  echo [ERROR] Python not found. Install Python 3.10+ from python.org and re-run.
  exit /b 1
)

%PYTHON% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" || (
  echo [ERROR] Python 3.10 or newer is required.
  exit /b 1
)

echo.
echo 1/4 Frontend: installing packages and building
cd /d "%ROOT%\frontend"

rem npm is a .cmd script, so it needs "call" or this script ends with it.
if exist package-lock.json (
  call npm ci || goto :fail
) else (
  call npm install || goto :fail
)

call npm run build || goto :fail
if not exist dist\index.html (
  echo [ERROR] The frontend build produced no dist\index.html.
  exit /b 1
)

echo.
echo 2/4 Backend: Python environment
cd /d "%ROOT%\backend"

if not exist venv\Scripts\python.exe (
  %PYTHON% -m venv venv || goto :fail
)

call venv\Scripts\activate.bat || goto :fail

python -m pip install --upgrade pip || goto :fail
rem One venv for both processes: start.bat runs the engine and the gateway
rem from it, so the gateway's packages go in here too.
python -m pip install -r requirements.txt -r "%ROOT%\requirements-client.txt" || goto :fail

echo.
echo 3/4 Configuration

if exist .env (
  echo    backend\.env exists - kept as it is
) else (
  copy /y .env.example .env >nul || goto :fail
  rem Edited from Python rather than batch: the secret can contain characters
  rem that batch string handling mangles. FRONTEND_URL moves to the engine's
  rem port, which serves the app on-premise; 5173 is the Vite dev server.
  python -c "import re, secrets, pathlib; p = pathlib.Path('.env'); s = p.read_text(encoding='utf-8'); s = re.sub(r'(?m)^JWT_SECRET=.*$', 'JWT_SECRET=' + secrets.token_urlsafe(48), s); s = re.sub(r'(?m)^FRONTEND_URL=.*$', 'FRONTEND_URL=http://localhost:8000', s); p.write_text(s, encoding='utf-8')" || goto :fail
  echo    wrote backend\.env with a new JWT_SECRET
)

echo.
echo 4/4 Models

rem The answer model, in Ollama.
set "MODEL="
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /b /c:"MAIN_LLM_MODEL=" .env`) do set "MODEL=%%b"
if not defined MODEL set "MODEL=llama3.2:latest"

where ollama >nul 2>&1
if errorlevel 1 (
  echo    [WARN] Ollama not found. Install it from https://ollama.com before starting.
) else (
  ollama list 2>nul | findstr /b /c:"%MODEL% " >nul
  if errorlevel 1 (
    ollama pull %MODEL%
    if errorlevel 1 (
      echo    [WARN] %MODEL% is missing and could not be downloaded.
      echo           Start Ollama and re-run, or copy the model in from a connected machine.
    ) else (
      echo    %MODEL%: downloaded
    )
  ) else (
    echo    %MODEL%: present
  )
)

rem The gateway's own models: MiniLM for semantic search (Chroma's cache) and
rem the cross-encoder reranker (Hugging Face's cache). Both download on first
rem use, which an air-gapped machine cannot do, so they are fetched now. A
rem failure here is not fatal - search falls back to keyword-only and
rem reranking switches off.
set "KRISH_RERANKER_MODEL="
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /b /c:"KRISH_RERANKER_MODEL=" .env`) do set "KRISH_RERANKER_MODEL=%%b"
if not defined KRISH_RERANKER_MODEL set "KRISH_RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2"

python -c "import os; from chromadb.utils.embedding_functions import DefaultEmbeddingFunction; DefaultEmbeddingFunction()(['warm up']); print('   semantic search model: ready'); from sentence_transformers import CrossEncoder; CrossEncoder(os.environ['KRISH_RERANKER_MODEL']); print('   reranker ' + os.environ['KRISH_RERANKER_MODEL'] + ': ready')"
if errorlevel 1 echo    [WARN] Could not fetch the search models; run install again when online.

echo.
echo Installation complete! Run start.bat to launch the AI engine.
exit /b 0

:fail
echo.
echo [ERROR] Installation failed at the step above. Fix it and re-run install.bat.
exit /b 1
