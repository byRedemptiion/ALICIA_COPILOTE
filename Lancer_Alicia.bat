@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\alicia.exe" goto install

rem Nouvelle version avec de nouvelles dependances ? (uv.lock different de celui installe)
fc /b "uv.lock" ".venv\uv.lock.installed" >nul 2>nul
if errorlevel 1 (
  echo Mise a jour des dependances d'Alicia...
  powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\setup.ps1" -Update
  if errorlevel 1 (
    echo.
    echo La mise a jour a echoue : envoie une capture de cette fenetre.
    pause
    exit /b 1
  )
)
goto run

:install
echo Alicia n'est pas encore installee sur ce PC : lancement de l'installation...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\setup.ps1"
if errorlevel 1 (
  echo.
  echo L'installation a echoue : envoie une capture de cette fenetre.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\alicia.exe" (
  echo Installation incomplete : .venv\Scripts\alicia.exe est introuvable.
  pause
  exit /b 1
)

:run
".venv\Scripts\alicia.exe" %*
if errorlevel 1 (
  echo.
  echo Alicia s'est arretee avec une erreur. Le journal est dans %LOCALAPPDATA%\Alicia\logs
  pause
)
