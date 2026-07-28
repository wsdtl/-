@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_BIN=%~dp0.venv\Scripts\python.exe"
set "NEEDS_INSTALL=0"
if not exist "%PYTHON_BIN%" (
    py -3 -m venv .venv
    if errorlevel 1 exit /b 1
    set "NEEDS_INSTALL=1"
)

"%PYTHON_BIN%" -c "import apscheduler, cryptography, fastapi, loguru, urllib3, uvicorn" >nul 2>&1
if errorlevel 1 set "NEEDS_INSTALL=1"

if "%NEEDS_INSTALL%"=="1" (
    "%PYTHON_BIN%" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 exit /b 1
)

"%PYTHON_BIN%" main.py
set "EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %EXIT_CODE%
