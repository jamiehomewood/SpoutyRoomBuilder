@echo off
setlocal
title Room Builder
REM Starts the Room Builder server and opens the builder in your browser.
REM Leave this window open while you use it (renders run from here). Close it to stop.

pushd "%~dp0" || (echo Could not open the folder "%~dp0". & goto :fail)
if not exist server.py (echo server.py is missing from "%CD%". & goto :fail)

REM Find a Python that really runs. The "python" Microsoft Store shortcut is skipped.
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"
if not defined PY python3 --version >nul 2>nul && set "PY=python3"
if not defined PY (
  echo Python was not found on this PC.
  echo Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^), then run this file again.
  goto :fail
)

start "" cmd /c "timeout /t 2 >nul & start http://localhost:8030/"
echo Using: %PY%
%PY% server.py
echo.
echo The server stopped ^(exit code %ERRORLEVEL%^). Any error is shown above.

:fail
echo.
pause
popd
endlocal
