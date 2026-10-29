@echo off
setlocal
cd /d "%~dp0"

rem Alice installee : on la lance directement depuis son environnement (pas besoin de uv).
if exist ".venv\Scripts\alice.exe" goto run

echo Alice n'est pas encore installee sur ce PC : lancement de l'installation...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\setup.ps1"
if errorlevel 1 (
  echo.
  echo L'installation a echoue : envoie une capture de cette fenetre.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\alice.exe" (
  echo Installation incomplete : .venv\Scripts\alice.exe est introuvable.
  pause
  exit /b 1
)

:run
".venv\Scripts\alice.exe" %*
if errorlevel 1 (
  echo.
  echo Alice s'est arretee avec une erreur. Le journal est dans %LOCALAPPDATA%\Alice\logs
  pause
)
