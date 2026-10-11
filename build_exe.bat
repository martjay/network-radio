@echo off
setlocal EnableDelayedExpansion
title BROADCAST - Build EXE

rem ===========================================================================
rem  BROADCAST - Windows executable builder
rem
rem  Produces a standalone distribution in  dist\Broadcast\  that runs on
rem  machines without Python installed. Requires the uv environment created by
rem  run.bat (or it will create one).
rem
rem  Usage:
rem      build_exe.bat            build the distribution
rem      build_exe.bat clean      remove build output first
rem ===========================================================================

cd /d "%~dp0"

set "VENV=.venv"
set "PY=%VENV%\Scripts\python.exe"
set "DIST=dist\Broadcast"
set "SPEC=packaging\broadcast.spec"
set "REQ=requirements-build.txt"

echo.
echo   ==========================================================
echo     BROADCAST - Build Windows EXE
echo   ==========================================================
echo.

if /i "%~1"=="clean" (
    echo   Removing previous build output ...
    if exist "build" rmdir /s /q "build"
    if exist "dist" rmdir /s /q "dist"
    echo.
)

rem --------------------------------------------------------------- uv check
where uv >nul 2>nul
if errorlevel 1 (
    echo   [ERROR] uv was not found on PATH.
    echo           Install it with:  winget install --id=astral-sh.uv -e
    echo.
    pause
    exit /b 1
)

set "UV_CACHE_DIR=%~dp0.uv-cache"
set "UV_LINK_MODE=copy"

rem --------------------------------------------------- virtual environment
if not exist "%PY%" (
    echo   [1/5] Creating virtual environment ...
    uv venv "%VENV%" --python 3.11 --allow-existing >nul 2>&1
    if not exist "%PY%" (
        uv venv "%VENV%" --allow-existing
        if not exist "%PY%" (
            echo   [ERROR] Could not create the virtual environment.
            pause
            exit /b 1
        )
    )
) else (
    echo   [1/5] Virtual environment ready.
)

rem ------------------------------------------------------- dependencies
echo   [2/5] Installing runtime and build dependencies ...
uv pip install --python "%PY%" -r requirements.txt >nul
if errorlevel 1 (
    echo   [ERROR] Could not install runtime dependencies.
    pause
    exit /b 1
)
uv pip install --python "%PY%" -r "%REQ%"
if errorlevel 1 (
    echo   [ERROR] Could not install build dependencies.
    echo           If you are behind a proxy, set HTTPS_PROXY first.
    pause
    exit /b 1
)

rem ------------------------------------------------------- sanity check
echo   [3/5] Verifying the application imports cleanly ...
"%PY%" -c "import sys; sys.path.insert(0, '.'); import radio.main_window, radio.proxy, radio.recorder; print('        imports OK')"
if errorlevel 1 (
    echo   [ERROR] The application failed to import. Fix the errors above first.
    pause
    exit /b 1
)

rem ------------------------------------------------------------- build
echo   [4/5] Building executable ^(this takes a few minutes^) ...
"%PY%" -m PyInstaller --clean --noconfirm --distpath dist --workpath build "%SPEC%"
if errorlevel 1 (
    echo.
    echo   [ERROR] PyInstaller build failed. See the output above.
    pause
    exit /b 1
)

if not exist "%DIST%\Broadcast.exe" (
    echo   [ERROR] Expected "%DIST%\Broadcast.exe" was not produced.
    pause
    exit /b 1
)

rem ------------------------------------------------------------- verify
echo   [5/6] Verifying the built executable ...
echo.
"%DIST%\Broadcast.exe" --selftest
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
    echo.
    echo   [ERROR] The built executable failed its self-test ^(code %CODE%^).
    echo           Run "%DIST%\Broadcast.exe" manually to see the error.
    pause
    exit /b %CODE%
)

echo.
echo   [6/6] Playing a live station through the packaged decoder ...
echo         ^(confirms the bundled FFmpeg backend really works^)
echo.
"%DIST%\Broadcast.exe" --playtest
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
    echo.
    echo   [WARNING] The play-test did not pass ^(code %CODE%^).
    echo             This usually means the network is unavailable or a proxy
    echo             is required, not that the build is broken.
    echo             The executable is still in "%DIST%".
    echo.
)

echo.
echo   ==========================================================
echo     Build complete
echo   ==========================================================
echo.
for %%F in ("%DIST%\Broadcast.exe") do echo     Executable : %%~fF  ^(%%~zF bytes^)
echo     Folder     : %CD%\%DIST%
echo.
echo   The whole "%DIST%" folder is the distribution.
echo   Copy it anywhere and run Broadcast.exe - no Python required.
echo.

endlocal
exit /b 0
