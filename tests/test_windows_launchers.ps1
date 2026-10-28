# Exercise the real launcher scripts with local doubles, without Windows or network.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ('alicia-launchers-' + [Guid]::NewGuid().ToString('N'))
$fixtureScripts = Join-Path $fixtureRoot 'scripts'
$fixtureEnv = Join-Path $fixtureRoot '.env'
$trackedVariables = @(
    'OLLAMA_HOST', 'OLLAMA_NO_CLOUD', 'ALICIA_AI_PROVIDER',
    'ALICIA_TTS_PROVIDER', 'ALICIA_STT_PROVIDER', 'ALICIA_OLLAMA_MODEL', 'ALICIA_OLLAMA_URL'
)
$originalVariables = @{}
foreach ($name in $trackedVariables) {
    $originalVariables[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$script:assertions = 0
$global:aliciaHarnessCalls = [Collections.Generic.List[object]]::new()
$global:aliciaHarnessRequests = [Collections.Generic.List[string]]::new()
$global:aliciaHarnessModelPresent = $true
$global:aliciaHarnessPrepareVoiceFails = $false

function Assert-That([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "Assertion failed: $Message" }
    $script:assertions++
}

function Reset-Fixture {
    $global:aliciaHarnessCalls.Clear()
    $global:aliciaHarnessRequests.Clear()
    $global:aliciaHarnessModelPresent = $true
    $global:aliciaHarnessPrepareVoiceFails = $false
    foreach ($name in $trackedVariables) {
        [Environment]::SetEnvironmentVariable($name, "before-test-$name", 'Process')
    }
}

function Assert-EnvironmentRestored {
    foreach ($name in $trackedVariables) {
        Assert-That ([Environment]::GetEnvironmentVariable($name, 'Process') -eq "before-test-$name") "Environment restored: $name"
    }
    Assert-That ([IO.File]::ReadAllText($fixtureEnv) -eq 'ALICIA_AI_PROVIDER=synthetic-user-setting') '.env contents preserved'
}

# Child script scopes resolve these functions before PowerShell cmdlets.
function Get-Command {
    [CmdletBinding()]
    param([string]$Name)
    if ($Name -eq 'uv.exe') { return [pscustomobject]@{ Source = $global:aliciaHarnessUv } }
    if ($Name -eq 'ollama.exe') { return [pscustomobject]@{ Source = $global:aliciaHarnessOllama } }
    throw "Unexpected tool lookup: $Name"
}

function Invoke-RestMethod {
    [CmdletBinding()]
    param([string]$Uri, [string]$Method, [int]$TimeoutSec)
    $global:aliciaHarnessRequests.Add($Uri)
    if ($Uri -eq 'http://127.0.0.1:11434/api/version') {
        return [pscustomobject]@{ version = 'test-local-server' }
    }
    if ($Uri -eq 'http://127.0.0.1:11434/api/tags') {
        $models = @()
        if ($global:aliciaHarnessModelPresent) { $models = @([pscustomobject]@{ name = 'qwen2.5vl:7b' }) }
        return [pscustomobject]@{ models = $models }
    }
    throw "Unexpected request blocked by launcher harness: $Uri"
}

function Start-Process { throw 'A ready local server must not be started again.' }
function Start-Sleep { throw 'A ready local server must not require sleeping.' }
function Add-Type {
    [CmdletBinding()]
    param([string]$AssemblyName)
    throw 'Native speech is intentionally excluded from this portable launcher test.'
}

try {
    New-Item -ItemType Directory -Path $fixtureScripts | Out-Null
    foreach ($name in @('setup_local.ps1', 'start_alicia.ps1')) {
        Copy-Item -LiteralPath (Join-Path $repositoryRoot "scripts/$name") -Destination (Join-Path $fixtureScripts $name)
    }
    [IO.File]::WriteAllText($fixtureEnv, 'ALICIA_AI_PROVIDER=synthetic-user-setting')
    $global:aliciaHarnessUv = Join-Path $fixtureRoot 'uv.ps1'
    $global:aliciaHarnessOllama = Join-Path $fixtureRoot 'ollama.ps1'
    $fakeBody = @'
$global:aliciaHarnessCalls.Add([pscustomobject]@{
    Tool = '__TOOL__'
    Arguments = @($args)
    AiProvider = $env:ALICIA_AI_PROVIDER
    TtsProvider = $env:ALICIA_TTS_PROVIDER
    SttProvider = $env:ALICIA_STT_PROVIDER
    Model = $env:ALICIA_OLLAMA_MODEL
    Url = $env:ALICIA_OLLAMA_URL
    OllamaHost = $env:OLLAMA_HOST
    NoCloud = $env:OLLAMA_NO_CLOUD
})
$global:LASTEXITCODE = 0
if ($global:aliciaHarnessPrepareVoiceFails -and $args -contains '--prepare-audio') {
    $global:LASTEXITCODE = 1
}
'@
    [IO.File]::WriteAllText($global:aliciaHarnessUv, $fakeBody.Replace('__TOOL__', 'uv'))
    [IO.File]::WriteAllText($global:aliciaHarnessOllama, $fakeBody.Replace('__TOOL__', 'ollama'))

    Reset-Fixture
    & (Join-Path $fixtureScripts 'setup_local.ps1') 3>$null 6>$null
    $pulls = @($global:aliciaHarnessCalls | Where-Object { $_.Arguments[0] -eq 'pull' })
    Assert-That ($pulls.Count -eq 0) 'Setup does not pull an installed model'
    $syncs = @($global:aliciaHarnessCalls | Where-Object { $_.Tool -eq 'uv' -and $_.Arguments[0] -eq 'sync' })
    Assert-That ($syncs.Count -eq 1) 'Setup installs dependencies once'
    Assert-That (($syncs[0].Arguments -join ' ') -eq 'sync --python 3.12 --frozen --extra dev') 'Frozen dependency command and Python version preserved'
    $voicePreparations = @($global:aliciaHarnessCalls | Where-Object { $_.Tool -eq 'uv' -and $_.Arguments -contains '--prepare-audio' })
    Assert-That ($voicePreparations.Count -eq 1) 'Setup explicitly prepares the neural local audio models once'
    Assert-That (($voicePreparations[0].Arguments -join ' ') -eq 'run --frozen alicia --prepare-audio') 'Audio preparation uses the installed locked application'
    Assert-That (@($global:aliciaHarnessCalls | Where-Object { $_.Arguments -contains '--prepare-voice' }).Count -eq 0) 'Setup does not prepare the old Vosk engine implicitly'
    Assert-EnvironmentRestored

    Reset-Fixture
    $global:aliciaHarnessModelPresent = $false
    & (Join-Path $fixtureScripts 'setup_local.ps1') 3>$null 6>$null
    $pulls = @($global:aliciaHarnessCalls | Where-Object { $_.Arguments[0] -eq 'pull' })
    Assert-That ($pulls.Count -eq 1) 'Setup pulls a missing model exactly once'
    Assert-That (($pulls[0].Arguments -join ' ') -eq 'pull qwen2.5vl:7b') 'Setup pulls the documented model'
    Assert-That ($pulls[0].OllamaHost -eq 'http://127.0.0.1:11434') 'Pull uses the local Ollama server'
    Assert-That ($pulls[0].NoCloud -eq '1') 'Cloud features disabled for explicit pull process'
    Assert-EnvironmentRestored

    Reset-Fixture
    & (Join-Path $fixtureScripts 'start_alicia.ps1') 3>$null 6>$null
    Assert-That ($global:aliciaHarnessCalls.Count -eq 1) 'Launch invokes only uv'
    $launch = $global:aliciaHarnessCalls[0]
    Assert-That ($launch.Tool -eq 'uv' -and ($launch.Arguments -join ' ') -eq 'run --frozen alicia') 'Launch command preserved'
    Assert-That ($launch.AiProvider -eq 'ollama' -and $launch.TtsProvider -eq 'kokoro' -and $launch.SttProvider -eq 'whisper') 'Launch forces free local vision, neural voice and recognition'
    Assert-That ($launch.Model -eq 'qwen2.5vl:7b') 'Launch uses checked model'
    Assert-That ($launch.Url -eq 'http://127.0.0.1:11434' -and $launch.OllamaHost -eq $launch.Url) 'Launch uses checked loopback server'
    Assert-That ($launch.NoCloud -eq '1') 'Launch disables cloud features'
    Assert-EnvironmentRestored

    Reset-Fixture
    & (Join-Path $fixtureScripts 'start_alicia.ps1') -Demo 3>$null 6>$null
    Assert-That (($global:aliciaHarnessCalls[0].Arguments -join ' ') -eq 'run --frozen alicia --demo') 'Demo switch forwarded'
    Assert-EnvironmentRestored

    Reset-Fixture
    $global:aliciaHarnessModelPresent = $false
    $missingFailed = $false
    try {
        & (Join-Path $fixtureScripts 'start_alicia.ps1') 3>$null 6>$null
    } catch {
        $missingFailed = $_.Exception.Message -match 'manque'
    }
    Assert-That $missingFailed 'Missing model produces a clear launch failure'
    Assert-That ($global:aliciaHarnessCalls.Count -eq 0) 'Missing model does not pull or launch uv'
    Assert-EnvironmentRestored

    Reset-Fixture
    $global:aliciaHarnessPrepareVoiceFails = $true
    $voicePreparationFailed = $false
    try {
        & (Join-Path $fixtureScripts 'setup_local.ps1') 3>$null 6>$null
    } catch {
        $voicePreparationFailed = $_.Exception.Message -match 'modeles audio'
    }
    Assert-That $voicePreparationFailed 'Failed voice preparation is not reported as a successful installation'
    Assert-EnvironmentRestored

    Write-Host "Launcher harness passed: 6 scenarios, $script:assertions assertions; no network, native speech or installed tools used."
} finally {
    foreach ($name in $trackedVariables) {
        [Environment]::SetEnvironmentVariable($name, $originalVariables[$name], 'Process')
    }
    if (Test-Path -LiteralPath $fixtureRoot) { Remove-Item -LiteralPath $fixtureRoot -Recurse -Force }
    Remove-Variable -Name aliciaHarnessCalls, aliciaHarnessRequests, aliciaHarnessModelPresent, aliciaHarnessPrepareVoiceFails, aliciaHarnessUv, aliciaHarnessOllama -Scope Global -ErrorAction SilentlyContinue
}
