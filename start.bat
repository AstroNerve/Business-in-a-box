@echo off
cd /d "%~dp0"
py -3 server.py
if errorlevel 1 (
  echo.
  echo Could not start the app. Install Python 3 from https://www.python.org/downloads/ and try again.
  pause
)
