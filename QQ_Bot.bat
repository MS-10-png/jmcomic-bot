@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title JM NoneBot Core Launcher

echo ==============================================
echo JM NoneBot Core Launcher
echo Folder: %CD%
echo ==============================================
echo.

set "PYTHON_EXE="
set "PYTHON_ARGS="

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" --version >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
    goto run
  )
)

where python >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_EXE=python"
  goto run
)

py -3 --version >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_EXE=py"
  set "PYTHON_ARGS=-3"
  goto run
)

echo [ERROR] Python was not found.
echo Install Python 3.10+ and enable "Add Python to PATH", then run this file again.
echo.
pause
exit /b 1

:run
echo [INFO] Python command: %PYTHON_EXE% %PYTHON_ARGS%
echo [INFO] Installing/checking bot dependencies...
"%PYTHON_EXE%" %PYTHON_ARGS% -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo [ERROR] Dependency installation failed.
  echo Please run this command manually:
  echo "%PYTHON_EXE%" %PYTHON_ARGS% -m pip install -r requirements.txt
  echo.
  pause
  exit /b 1
)

echo.
echo [INFO] Starting NoneBot...
if "%PYTHON_EXE%"=="py" (
  py %PYTHON_ARGS% "%~dp0bot.py"
) else (
  "%PYTHON_EXE%" "%~dp0bot.py"
)
set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo [INFO] NoneBot stopped. Exit code: %EXIT_CODE%
pause
exit /b %EXIT_CODE%
