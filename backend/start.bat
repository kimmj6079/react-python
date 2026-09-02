@echo off
rem =====================================================================
rem Start backend dev server in a new window: uvicorn --reload (:8000)
rem  - Runs check.bat first (ruff format + lint --fix). A lint failure
rem    does NOT block the server - it only warns. Fix before committing.
rem  - Also starts the Postgres container (db). If Docker Desktop is off,
rem    prints a warning and continues (chatbot works without DB).
rem  - After changing postgres/Dockerfile, run once manually:
rem    docker compose up -d --build db   (without --build the old image is reused)
rem  - To stop: stop.bat
rem =====================================================================
cd /d "%~dp0"

call "%~dp0check.bat"
if errorlevel 1 (
    echo [warn] lint errors remain - starting the server anyway. Fix them before committing.
)

docker compose -f "%~dp0..\docker-compose.yml" up -d db >nul 2>&1
if errorlevel 1 (
    echo [warn] Docker is not running - starting without DB. Chatbot works, items/RAG need the DB.
) else (
    echo [ok] Postgres container "db" is up
)

echo [backend] starting http://localhost:8000 in a new window...
start "react-python-backend" cmd /k "uv run uvicorn app.main:app --reload"
