[CmdletBinding()]
param([switch]$Demo)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$modelName = 'qwen2.5vl:7b'
$ollamaApi = 'http://127.0.0.1:11434'
$previousHost = $env:OLLAMA_HOST
$previousNoCloud = $env:OLLAMA_NO_CLOUD
$previousAiProvider = $env:ALICIA_AI_PROVIDER
$previousTtsProvider = $env:ALICIA_TTS_PROVIDER
$previousModel = $env:ALICIA_OLLAMA_MODEL
$previousUrl = $env:ALICIA_OLLAMA_URL

function Find-Tool([string]$Name, [string[]]$Candidates) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in $Candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    return $null
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
    # Explicit process settings also take precedence over old .env files.
    $env:ALICIA_AI_PROVIDER = 'ollama'
    $env:ALICIA_TTS_PROVIDER = 'windows'
    $env:ALICIA_OLLAMA_MODEL = $modelName
    $env:ALICIA_OLLAMA_URL = $ollamaApi
    $uvExecutable = Find-Tool 'uv.exe' @(
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\uv.exe",
        "$env:USERPROFILE\.local\bin\uv.exe"
    )
    if (-not $uvExecutable) { throw 'uv est absent. Lancez d abord .\scripts\setup_local.ps1.' }
    if (-not (Test-Ollama)) {
        $ollamaExecutable = Find-Tool 'ollama.exe' @(
            "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
            "$env:LOCALAPPDATA\Microsoft\WinGet\Links\ollama.exe"
        )
        if (-not $ollamaExecutable) { throw 'Ollama est absent. Lancez .\scripts\setup_local.ps1.' }
        Start-Process -FilePath $ollamaExecutable -ArgumentList 'serve' -WindowStyle Hidden | Out-Null
    }
    $serverReady = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if (Test-Ollama) { $serverReady = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $serverReady) { throw 'Ollama ne repond pas sur 127.0.0.1:11434. Ouvrez Ollama puis reessayez.' }
    $tags = Invoke-RestMethod -Uri "$ollamaApi/api/tags" -Method Get -TimeoutSec 10
    $installedModels = @($tags.models | ForEach-Object { $_.name })
    if ($installedModels -notcontains $modelName) {
        throw "Le modele local $modelName manque. Lancez .\scripts\setup_local.ps1 pour le telecharger."
    }
    if ($Demo) {
        & $uvExecutable run --frozen alicia --demo
    } else {
        & $uvExecutable run --frozen alicia
    }
    if ($LASTEXITCODE -ne 0) { throw "Alicia s'est terminee avec une erreur ($LASTEXITCODE). Consultez les logs locaux." }
} finally {
    $env:OLLAMA_HOST = $previousHost
    $env:OLLAMA_NO_CLOUD = $previousNoCloud
    $env:ALICIA_AI_PROVIDER = $previousAiProvider
    $env:ALICIA_TTS_PROVIDER = $previousTtsProvider
    $env:ALICIA_OLLAMA_MODEL = $previousModel
    $env:ALICIA_OLLAMA_URL = $previousUrl
    Pop-Location
}
