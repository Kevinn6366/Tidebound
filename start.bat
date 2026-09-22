@echo off
setlocal
cd /d "%~dp0"
if not "%~2"=="" goto usage
if not "%~1"=="" if not "%~1"=="--skip-db" goto usage
for %%T in (uv node npm) do (
    where %%T >nul 2>&1
    if errorlevel 1 (
        echo Missing command: %%T
        goto fail
    )
)
if not exist .env (
    echo Copy .env.example to .env and configure MySQL and model credentials first.
    goto fail
)
node -e "const [major, minor] = process.versions.node.split('.').map(Number); if (major < 22 || (major === 22 && minor < 12)) { console.error('Node.js 22.12 or newer required'); process.exit(1); }"
if errorlevel 1 goto fail
uv sync --locked
if errorlevel 1 goto fail
.venv\Scripts\python.exe -c "import socket; sockets = [socket.socket() for _ in range(2)]; [s.bind(('127.0.0.1', p)) for s, p in zip(sockets, (5201, 5173))]"
if errorlevel 1 goto fail
if "%~1"=="--skip-db" goto dependencies
docker info >nul
if errorlevel 1 goto fail
docker compose --env-file .env -p tidebound -f deploy/compose.mysql.yaml up -d --wait
if errorlevel 1 goto fail

:dependencies
call npm --prefix webfrontend ci
if errorlevel 1 goto fail
if not exist data mkdir data
if errorlevel 1 goto fail
start "Tidebound Backend" cmd /k ".venv\Scripts\python.exe -u -m uvicorn webapp.main:app --host 127.0.0.1 --port 5201 --no-access-log --no-proxy-headers >> data\agent-debug.log 2>&1"
start "Tidebound Frontend" cmd /k "cd webfrontend && npm run dev"
echo Starting Tidebound: http://127.0.0.1:5173/app/
echo Backend log: data\agent-debug.log. Press Ctrl+C in each service window to stop.
exit /b 0

:usage
echo Usage: start.bat [--skip-db]
:fail
echo Startup failed. Check the error above.
pause
exit /b 1
