@echo off
chcp 65001 >nul
rem Self-elevate so we can stop the (possibly elevated) manager and replace the exe.
net session >nul 2>&1
if not %errorlevel%==0 (
    echo Requesting administrator rights...
    powershell -Command "Start-Process '%~f0' -Verb runAs"
    exit /b
)

cd /d "%~dp0"

echo ==============================================
echo  Apply JMComicBotManager fix
echo ==============================================
echo.

rem 1) Stop the running manager.
taskkill /IM JMComicBotManager.exe /F >nul 2>&1
if %errorlevel%==0 (
    echo [1/3] Manager stopped.
) else (
    echo [1/3] Manager is not running.
)
timeout /t 1 /nobreak >nul

rem 2) Replace the exe (keep a backup of the old one).
if not exist "JMComicBotManager.new.exe" (
    echo [ERROR] JMComicBotManager.new.exe not found.
    echo         Compile BotManagerApp.cs first, or re-run the build step.
    pause
    exit /b 1
)
if exist "JMComicBotManager.exe.bak" del /f /q "JMComicBotManager.exe.bak"
move /y "JMComicBotManager.exe" "JMComicBotManager.exe.bak" >nul
move /y "JMComicBotManager.new.exe" "JMComicBotManager.exe" >nul
echo [2/3] Manager replaced. Old copy saved as JMComicBotManager.exe.bak.

rem 3) Start the new manager (already elevated, no second UAC).
start "" "JMComicBotManager.exe"
echo [3/3] New manager started.
echo.
echo Done. The manager now runs with administrator rights,
echo so NapCat can be started/stopped without repeated UAC prompts.
echo.
pause
