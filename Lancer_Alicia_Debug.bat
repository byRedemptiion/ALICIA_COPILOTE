@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_alicia.ps1"
set "aliciaExit=%ERRORLEVEL%"
echo.
if not "%aliciaExit%"=="0" (
    echo Alicia n'a pas pu demarrer. Consultez le message ci-dessus.
    echo Pour preparer les outils et les modeles locaux, utilisez Installer_Alicia.bat.
)
pause
exit /b %aliciaExit%
