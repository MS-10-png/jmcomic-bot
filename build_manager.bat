@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================
echo  Build JMComicBotManager.exe from source
echo ==============================================
echo.
echo The manager EXE is a build artifact and is not shipped in the repo,
echo so "start manager.bat" needs a compile first. This produces
echo JMComicBotManager.new.exe; run apply_fix.bat to swap it in.
echo.

if not exist "BotManagerApp.cs" (
  echo [ERROR] BotManagerApp.cs not found in %CD%
  pause
  exit /b 1
)

set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%CSC%" (
  echo [ERROR] csc.exe not found. Install .NET Framework 4.x first.
  pause
  exit /b 1
)

for %%F in ("%CSC%") do set "LIBDIR=%%~dpF"
echo [INFO] Compiler: %CSC%

"%CSC%" /nologo /codepage:65001 /target:winexe /optimize+ /out:JMComicBotManager.new.exe ^
  /lib:"%LIBDIR%" ^
  /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll ^
  BotManagerApp.cs

if errorlevel 1 (
  echo.
  echo [ERROR] Build failed. See the compiler output above.
  pause
  exit /b 1
)

echo.
echo [OK] Built JMComicBotManager.new.exe
echo      Next: run apply_fix.bat to replace the running EXE
echo            (it keeps a .bak backup and restarts the manager).
echo.
pause
