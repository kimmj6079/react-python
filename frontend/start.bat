@echo off
rem =====================================================================
rem Start frontend dev server in a new window: vite (:5173)
rem  - To stop: stop.bat
rem =====================================================================
cd /d "%~dp0"

echo [frontend] starting http://localhost:5173 in a new window...
start "react-python-frontend" cmd /k "npm run dev"
