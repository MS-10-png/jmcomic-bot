@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

for /f "delims=" %%E in ('dir /b /s "%~dp0NapCat.Shell\launcher.bat" 2^>nul') do (
  cd /d "%%~dpE"
  echo [INFO] Running: %%~fE 100000000
  echo [INFO] Working directory: %%~dpE
  echo.
  call "%%~fE" 100000000
  set "EXIT_CODE=!ERRORLEVEL!"
  echo.
  echo [INFO] NapCat Shell stopped. Exit code: !EXIT_CODE!
  pause
  exit /b !EXIT_CODE!
)

echo [ERROR] NapCat Shell launcher.bat was not found.
echo Run setup_napcat_shell.ps1 or Start_All.bat first.
echo.
pause
exit /b 1
