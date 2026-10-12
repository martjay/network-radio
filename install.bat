@echo off
setlocal EnableDelayedExpansion
title BROADCAST - Install

rem ===========================================================================
rem  BROADCAST - one-click dependency installer
rem
rem  Creates an isolated uv virtual environment and installs requirements.txt.
rem  Safe to run repeatedly: packages are only reinstalled when the lock hash
rem  of requirements.txt changes.
rem
rem  Requires uv  ->  https://docs.astral.sh/uv/
rem ===========================================================================

cd /d "%~dp0"

set "VENV=.venv"
set "PY=%VENV%\Scripts\python.exe"
set "STAMP=%VENV%\.requirements.sha"

echo.
echo   ==========================================================
echo     BROADCAST - Install
echo   ==========================================================
echo.

where uv >nul 2>nul
if errorlevel 1 (
    echo   [ERROR] uv was not found on PATH.
    echo.
    echo   Install it with one of the following, then run this file again:
    echo       winget install --id=astral-sh.uv -e
    echo       powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 ^| iex"
    echo.
    pause
    exit /b 1
)

set "UV_CACHE_DIR=%~dp0.uv-cache"
set "UV_LINK_MODE=copy"

if not exist "%PY%" (
    echo   [1/2] Creating virtual environment in "%VENV%" ...
    uv venv "%VENV%" --python 3.11 --allow-existing >nul 2>&1
    if not exist "%PY%" (
        echo         Python 3.11 not available, using the default interpreter ...
        uv venv "%VENV%" --allow-existing
        if not exist "%PY%" (
            echo.
            echo   [ERROR] Could not create the virtual environment.
            echo.
            pause
            exit /b 1
        )
    )
) else (
    echo   [1/2] Virtual environment ready.
)

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
    echo   [2/2] Installing dependencies ...
    uv pip install --python "%PY%" -r requirements.txt
    if errorlevel 1 (
        echo.
        echo   [ERROR] Dependency installation failed.
        echo.
        pause
        exit /b 1
    )
    >"%STAMP%" echo !NEWHASH!
) else (
    echo   [2/2] Dependencies up to date.
)

echo.
echo   [OK] Dependencies installed. Run run.bat to start the app.
echo.
endlocal
exit /b 0
