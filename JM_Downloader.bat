@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title JM Comic Downloader

echo ==============================================
echo JM Comic Downloader
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
echo.

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import requests; import Crypto.Cipher" >nul 2>nul
if errorlevel 1 (
  echo [INFO] Missing downloader dependencies. Installing requests and pycryptodome...
  "%PYTHON_EXE%" %PYTHON_ARGS% -m pip install requests pycryptodome
  if errorlevel 1 (
    echo.
    echo [ERROR] Dependency installation failed.
    echo Please run this command manually:
    echo "%PYTHON_EXE%" %PYTHON_ARGS% -m pip install requests pycryptodome
    echo.
    pause
    exit /b 1
  )
  echo.
)

"%PYTHON_EXE%" %PYTHON_ARGS% "%~dp0main.py" %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
pause
exit /b %EXIT_CODE%
