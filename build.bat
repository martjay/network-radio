@echo off
setlocal
cd /d "%~dp0"
rem Thin wrapper so the standard English build.bat name exists.
call "%~dp0build_exe.bat" %*
exit /b %ERRORLEVEL%
