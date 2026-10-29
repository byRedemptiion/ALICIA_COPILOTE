# Installation d'Alice sous Windows : uv, Python 3.12, dépendances, clé Gemini.
# Lancé par Installer_Alice.bat. Ne modifie aucune politique PowerShell globale.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

Step "Vérification de uv (gestionnaire Python)"
$env:Path = "$env:USERPROFILE\.local\bin;$env:LOCALAPPDATA\Programs\uv;$env:USERPROFILE\.cargo\bin;$env:Path"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv absent : installation depuis astral.sh..."
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    if ($LASTEXITCODE -ne 0) { throw "L'installation de uv a échoué (code $LASTEXITCODE)." }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv n'a pas pu être installé. Installe-le manuellement : https://docs.astral.sh/uv/"
    }
}
uv --version

Step "Installation de Python 3.12 et des dépendances (première fois : quelques minutes)"
uv sync --python 3.12 --frozen
if ($LASTEXITCODE -ne 0) { throw "uv sync a échoué (code $LASTEXITCODE)." }

Step "Vérification du module de capture Windows"
uv run --frozen python -c "import windows_capture; print('windows-capture OK')"
if ($LASTEXITCODE -ne 0) { throw "Le module windows-capture ne se charge pas." }

Step "Clé Gemini"
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
$envText = Get-Content ".env" -Raw
if ($envText -match "(?m)^GEMINI_API_KEY=\S+") {
    Write-Host "Une clé est déjà présente dans .env (non affichée)."
} else {
    Write-Host "Crée une clé gratuite sur https://aistudio.google.com  ->  'Get API key'."
    $key = Read-Host "Colle ta clé ici (ou Entrée pour le faire plus tard dans le fichier .env)"
    if ($key.Trim()) {
        $envText = $envText -replace "(?m)^GEMINI_API_KEY=.*$", "GEMINI_API_KEY=$($key.Trim())"
        Set-Content ".env" $envText -NoNewline -Encoding UTF8
        Write-Host "Clé enregistrée dans .env (fichier exclu de Git)."
    }
}

if ((Get-Content ".env" -Raw) -match "(?m)^GEMINI_API_KEY=\S+") {
    Step "Test de la clé : modèles Gemini accessibles"
    uv run --frozen alice-diag models
    if ($LASTEXITCODE -ne 0) { Write-Host "La clé n'a pas été acceptée : voir le message ci-dessus." -ForegroundColor Yellow }
}

Step "Test de l'interface (hors écran, IA factice)"
uv run --frozen alice --smoke-test
if ($LASTEXITCODE -ne 0) { throw "Le test de l'interface a échoué." }

Write-Host "`nInstallation terminée. Lance Alice avec Lancer_Alice.bat" -ForegroundColor Green
