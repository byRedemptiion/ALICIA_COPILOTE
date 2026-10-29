@echo off
cd /d "%~dp0"
uv run --frozen alice %*
if errorlevel 1 (
  echo.
  echo Alice s'est arretee avec une erreur. Le journal est dans %LOCALAPPDATA%\Alice\logs
  pause
)
