[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$modelName = 'qwen3-vl:8b'
$ollamaApi = 'http://127.0.0.1:11434'
$previousHost = $env:OLLAMA_HOST
$previousNoCloud = $env:OLLAMA_NO_CLOUD
$previousAiProvider = $env:ALICIA_AI_PROVIDER
$previousTtsProvider = $env:ALICIA_TTS_PROVIDER
$previousSttProvider = $env:ALICIA_STT_PROVIDER
$previousWhisperDevice = $env:ALICIA_WHISPER_DEVICE
$previousModel = $env:ALICIA_OLLAMA_MODEL
$previousUrl = $env:ALICIA_OLLAMA_URL
$previousCommandPath = $env:Path

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

function Install-DesktopShortcut {
    try {
        $shell = New-Object -ComObject WScript.Shell
        $shortcutPath = Join-Path ($shell.SpecialFolders.Item('Desktop')) 'Alicia.lnk'
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $shell.ExpandEnvironmentStrings('%SystemRoot%\System32\wscript.exe')
        $shortcut.Arguments = '"' + (Join-Path $projectRoot 'Lancer_Alicia.vbs') + '"'
        $shortcut.WorkingDirectory = $projectRoot
        $shortcut.WindowStyle = 7
        $shortcut.Description = 'Alicia - copilote local gratuit'
        $shortcut.IconLocation = (Join-Path $projectRoot 'src\alicia\assets\alicia.ico') + ',0'
        $shortcut.Save()
        Write-Host 'Raccourci Alicia cree sur le Bureau : lancement sans terminal.'
    } catch {
        # A managed or read-only Desktop does not prevent using the application.
        Write-Warning 'Le raccourci Bureau n a pas pu etre cree. Lancez Lancer_Alicia.vbs dans le dossier Alicia.'
    }
}

Push-Location $projectRoot
try {
    $env:OLLAMA_HOST = $ollamaApi
    $env:OLLAMA_NO_CLOUD = '1'
    $env:ALICIA_AI_PROVIDER = 'ollama'
    $env:ALICIA_TTS_PROVIDER = 'chatterbox'
    $env:ALICIA_STT_PROVIDER = 'whisper'
    $env:ALICIA_WHISPER_DEVICE = 'auto'
    $env:ALICIA_OLLAMA_MODEL = $modelName
    $env:ALICIA_OLLAMA_URL = $ollamaApi
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

    # A fallback uv.exe path may not be on PATH yet. The isolated voice installer
    # discovers uv in a child Python process, so expose the exact tool found above.
    $uvDirectory = Split-Path -Parent $uvExecutable
    $env:Path = $uvDirectory + [IO.Path]::PathSeparator + $env:Path

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

    Write-Host 'Preparation de Whisper Turbo pour la reconnaissance et de Chatterbox pour la voix francaise expressive...'
    & $uvExecutable run --frozen alicia --prepare-audio
    if ($LASTEXITCODE -ne 0) { throw 'Preparation des modeles audio impossible. Consultez le message puis relancez Installer_Alicia.bat.' }

    Install-DesktopShortcut

    # Existing user configuration is intentionally preserved.
    Write-Host ''
    Write-Host 'Installation terminee. Aucun fichier .env existant n a ete modifie.'
    Write-Host 'La voix francaise Chatterbox et la reconnaissance Whisper Turbo restent sur votre PC.'
    Write-Host 'Alicia observe l ecran principal et active le microphone au lancement. Stop coupe les deux.'
    Write-Host 'La recherche web reste desactivee tant que vous ne l autorisez pas dans Alicia.'
    Write-Host 'Pour lancer Alicia sans terminal : raccourci Alicia ou Lancer_Alicia.vbs.'
    Write-Host 'Pour afficher un diagnostic : Lancer_Alicia_Debug.bat.'
} finally {
    $env:OLLAMA_HOST = $previousHost
    $env:OLLAMA_NO_CLOUD = $previousNoCloud
    $env:ALICIA_AI_PROVIDER = $previousAiProvider
    $env:ALICIA_TTS_PROVIDER = $previousTtsProvider
    $env:ALICIA_STT_PROVIDER = $previousSttProvider
    $env:ALICIA_WHISPER_DEVICE = $previousWhisperDevice
    $env:ALICIA_OLLAMA_MODEL = $previousModel
    $env:ALICIA_OLLAMA_URL = $previousUrl
    $env:Path = $previousCommandPath
    Pop-Location
}
