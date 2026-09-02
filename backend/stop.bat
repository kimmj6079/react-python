@echo off
rem =====================================================================
rem Stop backend dev server: kill the process tree LISTENING on port 8000.
rem  - Does NOT touch the DB container (to stop it: docker compose stop db)
rem  - The console window that ran the server stays open - just close it.
rem  - Caution: if another app uses port 8000, that app gets killed.
rem =====================================================================
set "PORT=8000"
set "KILLED="

for /f "tokens=5" %%a in ('netstat -aon ^| findstr /C:":%PORT% " ^| findstr LISTENING') do (
    taskkill /F /T /PID %%a >nul 2>&1
    set "KILLED=1"
)

if defined KILLED (
    echo [backend] server on port %PORT% stopped.
) else (
    echo [backend] no server is listening on port %PORT%.
)
