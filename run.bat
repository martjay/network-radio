@echo off
setlocal EnableDelayedExpansion
title BROADCAST - Network Radio

rem ===========================================================================
rem  BROADCAST - one-click launcher
rem
rem  Creates an isolated uv virtual environment, installs the dependencies,
rem  and starts the application. Safe to run repeatedly: the environment is
rem  reused and packages are only reinstalled when requirements.txt changes.
rem
rem  Requires uv  ->  https://docs.astral.sh/uv/
rem ===========================================================================

cd /d "%~dp0"

set "VENV=.venv"
set "PY=%VENV%\Scripts\python.exe"
set "STAMP=%VENV%\.requirements.sha"
set "APP=main.py"

echo.
echo   ==========================================================
echo     BROADCAST - Network Radio
echo   ==========================================================
echo.

rem --------------------------------------------------------------- uv check
where uv >nul 2>nul
if errorlevel 1 (
    echo   [ERROR] uv was not found on PATH.
    echo.
    echo   uv is required to manage the virtual environment.
    echo   Install it with one of the following, then run this file again:
    echo.
    echo       winget install --id=astral-sh.uv -e
    echo.
    echo       powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 ^| iex"
    echo.
    echo   More info: https://docs.astral.sh/uv/getting-started/installation/
    echo.
    pause
    exit /b 1
)

rem ----------------------------------------------------------------- cache
rem  Prefer a cache inside the project. This keeps the launcher working when
rem  the default per-user cache location is unwritable (locked-down machines,
rem  roaming profiles, restricted sandboxes), and it makes the checkout
rem  self-contained and easy to delete.
set "UV_CACHE_DIR=%~dp0.uv-cache"
set "UV_LINK_MODE=copy"

rem --------------------------------------------------- virtual environment
if not exist "%PY%" (
    echo   [1/3] Creating virtual environment in "%VENV%" ...
    uv venv "%VENV%" --python 3.11 --allow-existing >nul 2>&1
    if not exist "%PY%" (
        echo         Python 3.11 not available, using the default interpreter ...
        uv venv "%VENV%" --allow-existing
        if not exist "%PY%" (
            echo.
            echo   [ERROR] Could not create the virtual environment.
            echo           Run the command above manually to see the reason.
            echo.
            pause
            exit /b 1
        )
    )
) else (
    echo   [1/3] Virtual environment ready.
)

rem ------------------------------------------------------- dependencies
rem  Reinstall only when requirements.txt differs from the recorded hash.
set "NEED_INSTALL=1"
set "NEWHASH="
for /f "skip=1 delims=" %%H in ('certutil -hashfile requirements.txt SHA256 2^>nul') do (
    if not defined NEWHASH set "NEWHASH=%%H"
)
set "NEWHASH=!NEWHASH: =!"

if exist "%STAMP%" (
    set "OLDHASH="
    set /p OLDHASH=<"%STAMP%"
    if "!OLDHASH!"=="!NEWHASH!" set "NEED_INSTALL=0"
)

if "!NEED_INSTALL!"=="1" (
    echo   [2/3] Installing dependencies ^(first run may take a minute^) ...
    uv pip install --python "%PY%" -r requirements.txt
    if errorlevel 1 (
        echo.
        echo   [ERROR] Dependency installation failed.
        echo.
        echo   If you are behind a network that needs a proxy, set one first:
        echo       set HTTPS_PROXY=http://127.0.0.1:7890
        echo       set HTTP_PROXY=http://127.0.0.1:7890
        echo   then run this file again.
        echo.
        pause
        exit /b 1
    )
    >"%STAMP%" echo !NEWHASH!
) else (
    echo   [2/3] Dependencies up to date.
)

rem ------------------------------------------------------------- launch
echo   [3/3] Starting BROADCAST ...
echo.
"%PY%" "%APP%" %*
set "CODE=%ERRORLEVEL%"

if not "%CODE%"=="0" (
    echo.
    echo   ==========================================================
    echo     The application exited with code %CODE%.
    echo   ==========================================================
    echo.
    echo   Diagnostics:
    echo     - Python:
    "%PY%" -c "import sys; print('        ', sys.version)"
    echo     - PySide6:
    "%PY%" -c "import PySide6; print('        ', PySide6.__version__)" 2>nul
    echo.
    pause
    exit /b %CODE%
)

endlocal
exit /b 0
