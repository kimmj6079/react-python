@echo off
rem =====================================================================
rem Format + lint the backend (run before committing).
rem  - ruff format .      : auto-format (rewrites files in place)
rem  - ruff check --fix . : lint; auto-fixes what is safe, fails on the rest
rem  - CI runs "ruff check ." (ci.yml) - passing here means CI lint passes.
rem =====================================================================
cd /d "%~dp0"

echo [1/2] ruff format...
uv run ruff format .
if errorlevel 1 exit /b 1

echo [2/2] ruff check --fix...
uv run ruff check --fix .
if errorlevel 1 (
    echo [fail] lint errors remain that auto-fix could not solve - fix them manually.
    exit /b 1
)

echo [ok] format + lint passed
