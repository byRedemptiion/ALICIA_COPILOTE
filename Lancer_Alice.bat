@echo off
setlocal
cd /d "%~dp0"
rem uv s'installe dans le profil utilisateur : on l'ajoute au PATH sans attendre un redemarrage.
set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\Programs\uv;%USERPROFILE%\.cargo\bin;%PATH%"

where uv >nul 2>nul
if errorlevel 1 goto install
if not exist ".venv\Scripts\python.exe" goto install
goto run

:install
echo Alice n'est pas encore installee sur ce PC : lancement de l'installation...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\setup.ps1"
if errorlevel 1 (
  echo.
  echo L'installation a echoue : envoie une capture de cette fenetre.
  pause
  exit /b 1
)
where uv >nul 2>nul
if errorlevel 1 (
  echo uv reste introuvable. Ferme cette fenetre et relance Lancer_Alice.bat.
  pause
  exit /b 1
)

:run
uv run --frozen alice %*
if errorlevel 1 (
  echo.
  echo Alice s'est arretee avec une erreur. Le journal est dans %LOCALAPPDATA%\Alice\logs
  pause
)
