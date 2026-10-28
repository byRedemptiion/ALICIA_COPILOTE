[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$modelName = 'qwen2.5vl:7b'
$ollamaApi = 'http://127.0.0.1:11434'
$previousHost = $env:OLLAMA_HOST
$previousNoCloud = $env:OLLAMA_NO_CLOUD

function Refresh-CommandPath {
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machinePath;$userPath;$env:Path"
}

function Find-Tool([string]$Name, [string[]]$Candidates) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in $Candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    return $null
}

function Install-Tool([string]$PackageId) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'winget est absent. Installez App Installer depuis Microsoft Store, puis relancez ce script.'
    }
    & winget install --id $PackageId --exact --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) { throw "Installation de $PackageId impossible. Corrigez le message winget puis relancez." }
    Refresh-CommandPath
}

function Test-Ollama {
    try {
        $version = Invoke-RestMethod -Uri "$ollamaApi/api/version" -Method Get -TimeoutSec 3
        return [bool]$version.version
    } catch { return $false }
}

Push-Location $projectRoot
try {
    $env:OLLAMA_HOST = $ollamaApi
    $env:OLLAMA_NO_CLOUD = '1'
    Write-Host 'Alicia : preparation du mode local gratuit, sans cle API.'
    Write-Host 'Cette installation telecharge les outils, le modele visuel et les modeles audio locaux.'

    $uvCandidates = @(
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\uv.exe",
        "$env:USERPROFILE\.local\bin\uv.exe"
    )
    $uvExecutable = Find-Tool 'uv.exe' $uvCandidates
    if (-not $uvExecutable) {
        Install-Tool 'astral-sh.uv'
        $uvExecutable = Find-Tool 'uv.exe' $uvCandidates
    }
    if (-not $uvExecutable) { throw 'uv reste introuvable. Fermez et rouvrez PowerShell puis relancez.' }

    $ollamaCandidates = @(
        "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\ollama.exe"
    )
    $ollamaExecutable = Find-Tool 'ollama.exe' $ollamaCandidates
    if (-not $ollamaExecutable) {
        Install-Tool 'Ollama.Ollama'
        $ollamaExecutable = Find-Tool 'ollama.exe' $ollamaCandidates
    }
    if (-not $ollamaExecutable) { throw 'Ollama reste introuvable. Fermez et rouvrez PowerShell puis relancez.' }

    & $uvExecutable --version
    if ($LASTEXITCODE -ne 0) { throw 'uv ne peut pas demarrer.' }
    & $ollamaExecutable --version
    if ($LASTEXITCODE -ne 0) { throw 'Ollama ne peut pas demarrer.' }

    if (-not (Test-Ollama)) {
        Write-Host 'Demarrage du service Ollama sur ce PC...'
        Start-Process -FilePath $ollamaExecutable -ArgumentList 'serve' -WindowStyle Hidden | Out-Null
    }
    $serverReady = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if (Test-Ollama) { $serverReady = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $serverReady) { throw 'Ollama ne repond pas sur 127.0.0.1:11434. Ouvrez Ollama puis relancez.' }

    $tags = Invoke-RestMethod -Uri "$ollamaApi/api/tags" -Method Get -TimeoutSec 10
    $installedModels = @($tags.models | ForEach-Object { $_.name })
    if ($installedModels -notcontains $modelName) {
        Write-Host "Telechargement initial de $modelName. Aucun compte ni abonnement n'est requis."
        # Force this CLI operation to use the same local server validated above.
        & $ollamaExecutable pull $modelName
        if ($LASTEXITCODE -ne 0) { throw 'Le telechargement du modele a echoue. Verifiez Internet et relancez le script.' }
    } else {
        Write-Host "Modele $modelName deja installe : aucun nouveau telechargement."
    }

    & $uvExecutable sync --python 3.12 --frozen --extra dev
    if ($LASTEXITCODE -ne 0) { throw 'Installation des dependances Alicia impossible.' }

    Write-Host 'Preparation de Whisper pour la reconnaissance et de Kokoro pour la voix neuronale francaise...'
    & $uvExecutable run --frozen alicia --prepare-audio
    if ($LASTEXITCODE -ne 0) { throw 'Preparation des modeles audio impossible. Consultez le message puis relancez Installer_Alicia.bat.' }

    # Existing user configuration is intentionally preserved.
    Write-Host ''
    Write-Host 'Installation terminee. Aucun fichier .env existant n a ete modifie.'
    Write-Host 'La voix feminine francaise Kokoro et la reconnaissance Whisper restent sur votre PC.'
    Write-Host 'Alicia observe l ecran principal et active le microphone au lancement. Stop coupe les deux.'
    Write-Host 'La recherche web reste desactivee tant que vous ne l autorisez pas dans Alicia.'
    Write-Host 'Pour lancer Alicia : .\scripts\start_alicia.ps1'
} finally {
    $env:OLLAMA_HOST = $previousHost
    $env:OLLAMA_NO_CLOUD = $previousNoCloud
    Pop-Location
}
