@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title JM Comic QQ Bot - All In One

echo ==============================================
echo JM Comic QQ Bot - All In One
echo Folder: %CD%
echo ==============================================
echo.

set "PYTHON_EXE="
set "PYTHON_ARGS="

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" --version >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
    goto python_found
  )
)

where python >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_EXE=python"
  goto python_found
)

py -3 --version >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_EXE=py"
  set "PYTHON_ARGS=-3"
  goto python_found
)

echo [ERROR] Python was not found.
echo Install Python 3.10+ and enable "Add Python to PATH", then run this file again.
echo.
pause
exit /b 1

:python_found
echo [INFO] Python command: %PYTHON_EXE% %PYTHON_ARGS%
echo [INFO] Checking Python dependencies...
"%PYTHON_EXE%" %PYTHON_ARGS% -c "import nonebot; import nonebot.adapters.onebot; import requests; import PIL; import Crypto.Cipher; import bs4" >nul 2>nul
if errorlevel 1 (
  echo [INFO] Missing dependencies. Installing...
  "%PYTHON_EXE%" %PYTHON_ARGS% -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo [ERROR] Python dependency installation failed.
    pause
    exit /b 1
  )
)

echo.
echo [INFO] Setting up NapCat Shell...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_napcat_shell.ps1"
if errorlevel 1 (
  echo.
  echo [ERROR] NapCat Shell setup failed.
  pause
  exit /b 1
)

echo.
echo [INFO] Starting NoneBot...
if "%PYTHON_EXE%"=="py" (
  start "NoneBot" cmd /K py %PYTHON_ARGS% "%~dp0bot.py"
) else (
  start "NoneBot" cmd /K ""%PYTHON_EXE%" "%~dp0bot.py""
)

timeout /t 3 /nobreak >nul

echo [INFO] Starting NapCatQQ...
start "NapCatQQ" cmd /K call "%~dp0Run_NapCat_Shell.bat"
goto started

:started
echo.
echo [OK] Started.
echo Keep the NoneBot and NapCatQQ windows open.
echo Login QQ 100000000 in the NapCatQQ window or WebUI.
pause
exit /b 0
