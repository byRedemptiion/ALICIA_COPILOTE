# Installation d'ALICIA sous Windows : uv, Python 3.12, dépendances, modèles vocaux.
# -Installer : lancé par ALICIA-Setup.exe (sans question : l'IA est choisie dans l'installateur).
# -Update    : mise à jour des dépendances seulement (lancé par Lancer_Alicia.bat).
# Sans option : installation depuis le dossier source (Installer_Alicia.bat).
# Ne modifie aucune politique PowerShell globale.
param([switch]$Update, [switch]$Installer)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if ($Installer) { Start-Transcript -Path (Join-Path $root "install.log") -Force | Out-Null }

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

try {
    Step "Vérification de uv (gestionnaire Python)"
    # uv fourni avec l'installateur (bin\uv.exe), sinon celui de l'utilisateur.
    $env:Path = "$root\bin;$env:USERPROFILE\.local\bin;$env:LOCALAPPDATA\Programs\uv;$env:USERPROFILE\.cargo\bin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host "uv absent : installation depuis astral.sh..."
        powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
        if ($LASTEXITCODE -ne 0) { throw "L'installation de uv a échoué (code $LASTEXITCODE)." }
        if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
            throw "uv n'a pas pu être installé. Installe-le manuellement : https://docs.astral.sh/uv/"
        }
    }
    uv --version

    Step "Python 3.12 et composants d'ALICIA (première fois : quelques minutes)"
    uv sync --python 3.12 --frozen
    if ($LASTEXITCODE -ne 0) { throw "uv sync a échoué (code $LASTEXITCODE). Vérifie ta connexion Internet." }
    if (-not (Test-Path ".venv\Scripts\alicia-gui.exe")) {
        # Lanceur sans terminal ajouté par une mise à jour : on réinstalle le paquet d'ALICIA.
        uv sync --python 3.12 --frozen --reinstall-package alicia-copilot
    }

    Step "Modèles vocaux locaux (compréhension de ta voix, voix d'ALICIA) : environ 2 Go la première fois"
    uv run --frozen alicia-diag prepare-voice
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Les modèles vocaux n'ont pas pu être téléchargés : ALICIA réessaiera au lancement." -ForegroundColor Yellow
    }

    if (-not $Installer) {
        Step "Raccourci ALICIA sur le Bureau"
        try {
            $desktop = [Environment]::GetFolderPath("Desktop")
            $shell = New-Object -ComObject WScript.Shell
            $link = $shell.CreateShortcut((Join-Path $desktop "ALICIA.lnk"))
            $link.TargetPath = Join-Path $root ".venv\Scripts\alicia-gui.exe"
            $link.WorkingDirectory = $root
            $link.IconLocation = (Join-Path $root "src\alicia\assets\alicia.ico") + ",0"
            $link.Description = "ALICIA, copilote de jeu"
            $link.Save()
            Write-Host "Raccourci ALICIA créé sur le Bureau."
        } catch {
            Write-Host "Raccourci non créé : $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
    Copy-Item "uv.lock" ".venv\uv.lock.installed" -Force
    if ($Update) {
        Write-Host "`nComposants à jour." -ForegroundColor Green
        exit 0
    }

    Step "Vérification du module de capture Windows"
    uv run --frozen python -c "import windows_capture; print('windows-capture OK')"
    if ($LASTEXITCODE -ne 0) { throw "Le module windows-capture ne se charge pas." }

    if ($Installer) {
        Step "IA choisie dans l'installateur"
        uv run --frozen alicia-diag setup-ai
        if ($LASTEXITCODE -ne 0) { Write-Host "Choix de l'IA à refaire dans ALICIA (bouton IA)." -ForegroundColor Yellow }
    } else {
        Step "Clé Gemini"
        if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
        $envText = Get-Content ".env" -Raw
        if ($envText -match "(?m)^GEMINI_API_KEY=\S+") {
            Write-Host "Une clé est déjà présente dans .env (non affichée)."
        } else {
            Write-Host "Tu pourras coller ta clé Gemini au premier lancement d'ALICIA (bouton IA)."
        }
    }

    Step "Test de l'interface (hors écran, IA factice)"
    uv run --frozen alicia --smoke-test
    if ($LASTEXITCODE -ne 0) { throw "Le test de l'interface a échoué." }

    Write-Host "`nInstallation terminée." -ForegroundColor Green
    exit 0
} catch {
    Write-Host "`nERREUR : $($_.Exception.Message)" -ForegroundColor Red
    if ($Installer) { Write-Host "Journal complet : $root\install.log" }
    exit 1
} finally {
    if ($Installer) { Stop-Transcript | Out-Null }
}
