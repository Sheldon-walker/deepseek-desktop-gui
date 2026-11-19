@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)
if "%~1"=="" (
  "%PY%" cli.py
  echo.
  pause
) else (
  "%PY%" cli.py %*
  if errorlevel 1 pause
)
