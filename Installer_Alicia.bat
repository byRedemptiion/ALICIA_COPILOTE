@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_local.ps1"
set "aliciaExit=%ERRORLEVEL%"
echo.
if not "%aliciaExit%"=="0" (
    echo Installation interrompue. Consultez le message ci-dessus puis relancez Installer_Alicia.bat.
    pause
) else (
    echo Installation terminee. Double-cliquez maintenant sur Alicia ou Lancer_Alicia.vbs.
)
exit /b %aliciaExit%
