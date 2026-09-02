@echo off
rem =====================================================================
rem Stop frontend dev server: kill the process tree LISTENING on port 5173.
rem  - Caution: if 5173 was busy, vite moves to 5174 - this script will not
rem    find it. In that case press Ctrl+C in the server window instead.
rem =====================================================================
set "PORT=5173"
set "KILLED="

for /f "tokens=5" %%a in ('netstat -aon ^| findstr /C:":%PORT% " ^| findstr LISTENING') do (
    taskkill /F /T /PID %%a >nul 2>&1
    set "KILLED=1"
)

if defined KILLED (
    echo [frontend] server on port %PORT% stopped.
) else (
    echo [frontend] no server is listening on port %PORT%.
)
