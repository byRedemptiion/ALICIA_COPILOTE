# Exercise the real launcher scripts with local doubles, without Windows or network.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ('alicia launchers accents é ' + [Guid]::NewGuid().ToString('N'))
$fixtureScripts = Join-Path $fixtureRoot 'scripts'
$fixtureEnv = Join-Path $fixtureRoot '.env'
$originalCommandPath = $env:Path
$trackedVariables = @(
    'OLLAMA_HOST', 'OLLAMA_NO_CLOUD', 'ALICIA_AI_PROVIDER',
    'ALICIA_TTS_PROVIDER', 'ALICIA_STT_PROVIDER', 'ALICIA_WHISPER_DEVICE', 'ALICIA_OLLAMA_MODEL', 'ALICIA_OLLAMA_URL'
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
$global:aliciaHarnessProcessExitCode = 0
$global:aliciaHarnessProcesses = [Collections.Generic.List[object]]::new()
$global:aliciaHarnessShortcuts = [Collections.Generic.List[object]]::new()
$global:aliciaHarnessServerReady = $true
$global:aliciaHarnessServerStarts = [Collections.Generic.List[object]]::new()

function Assert-That([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "Assertion failed: $Message" }
    $script:assertions++
}

function Reset-Fixture {
    $env:Path = $originalCommandPath
    $global:aliciaHarnessCalls.Clear()
    $global:aliciaHarnessRequests.Clear()
    $global:aliciaHarnessModelPresent = $true
    $global:aliciaHarnessPrepareVoiceFails = $false
    $global:aliciaHarnessProcessExitCode = 0
    $global:aliciaHarnessProcesses.Clear()
    $global:aliciaHarnessShortcuts.Clear()
    $global:aliciaHarnessServerReady = $true
    $global:aliciaHarnessServerStarts.Clear()
    foreach ($name in $trackedVariables) {
        [Environment]::SetEnvironmentVariable($name, "before-test-$name", 'Process')
    }
}

function Assert-EnvironmentRestored {
    foreach ($name in $trackedVariables) {
        Assert-That ([Environment]::GetEnvironmentVariable($name, 'Process') -eq "before-test-$name") "Environment restored: $name"
    }
    Assert-That ($env:Path -eq $originalCommandPath) 'Original command PATH restored after success or failure'
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
        if (-not $global:aliciaHarnessServerReady) { throw 'Local test server is not ready yet.' }
        return [pscustomobject]@{ version = 'test-local-server' }
    }
    if ($Uri -eq 'http://127.0.0.1:11434/api/tags') {
        $models = @()
        if ($global:aliciaHarnessModelPresent) { $models = @([pscustomobject]@{ name = 'qwen3-vl:8b' }) }
        return [pscustomobject]@{ models = $models }
    }
    throw "Unexpected request blocked by launcher harness: $Uri"
}

function Start-Process {
    [CmdletBinding()]
    param([string]$FilePath, [string[]]$ArgumentList, [string]$WorkingDirectory, [string]$WindowStyle, [switch]$Wait, [switch]$PassThru)
    if ($FilePath -eq $global:aliciaHarnessOllama -and ($ArgumentList -join ' ') -eq 'serve') {
        if ($global:aliciaHarnessServerReady) { throw 'A ready local server must not be started again.' }
        $global:aliciaHarnessServerStarts.Add([pscustomobject]@{ WindowStyle = $WindowStyle })
        $global:aliciaHarnessServerReady = $true
        return
    }
    if ((Split-Path -Leaf $FilePath) -ne 'pythonw.exe') {
        throw 'A ready local server must not be started again.'
    }
    $global:aliciaHarnessProcesses.Add([pscustomobject]@{
        FilePath = $FilePath
        Arguments = @($ArgumentList)
        WorkingDirectory = $WorkingDirectory
        WindowStyle = $WindowStyle
        Wait = [bool]$Wait
        PassThru = [bool]$PassThru
        AiProvider = $env:ALICIA_AI_PROVIDER
        TtsProvider = $env:ALICIA_TTS_PROVIDER
        SttProvider = $env:ALICIA_STT_PROVIDER
        WhisperDevice = $env:ALICIA_WHISPER_DEVICE
    })
    return [pscustomobject]@{ ExitCode = $global:aliciaHarnessProcessExitCode }
}
function Start-Sleep { throw 'A ready local server must not require sleeping.' }
function Add-Type {
    [CmdletBinding()]
    param([string]$AssemblyName)
    throw 'Native speech is intentionally excluded from this portable launcher test.'
}

function New-Object {
    [CmdletBinding()]
    param([string]$ComObject)
    if ($ComObject -ne 'WScript.Shell') { throw "Unexpected COM object: $ComObject" }
    $folders = [pscustomobject]@{}
    $folders | Add-Member ScriptMethod Item {
        param([string]$Name)
        if ($Name -ne 'Desktop') { throw 'Only the Desktop folder is expected.' }
        return $global:aliciaHarnessDesktop
    }
    $shell = [pscustomobject]@{ SpecialFolders = $folders }
    $shell | Add-Member ScriptMethod ExpandEnvironmentStrings {
        param([string]$Value)
        if ($Value -ne '%SystemRoot%\System32\wscript.exe') { throw 'Only the Windows script host is expected.' }
        return 'C:\Windows\System32\wscript.exe'
    }
    $shell | Add-Member ScriptMethod CreateShortcut {
        param([string]$Path)
        $shortcut = [pscustomobject]@{
            Path = $Path; TargetPath = ''; Arguments = ''; WorkingDirectory = ''
            WindowStyle = 0; Description = ''; IconLocation = ''
        }
        $shortcut | Add-Member ScriptMethod Save { $global:aliciaHarnessShortcuts.Add($this) }
        return $shortcut
    }
    return $shell
}

try {
    New-Item -ItemType Directory -Path $fixtureScripts | Out-Null
    $global:aliciaHarnessDesktop = Join-Path $fixtureRoot 'Desktop'
    $pythonDirectory = Join-Path $fixtureRoot '.venv/Scripts'
    New-Item -ItemType Directory -Path $pythonDirectory, $global:aliciaHarnessDesktop | Out-Null
    $pythonExecutable = Join-Path $pythonDirectory 'pythonw.exe'
    [IO.File]::WriteAllText($pythonExecutable, 'portable test fixture only')
    foreach ($name in @('setup_local.ps1', 'start_alicia.ps1')) {
        Copy-Item -LiteralPath (Join-Path $repositoryRoot "scripts/$name") -Destination (Join-Path $fixtureScripts $name)
    }
    [IO.File]::WriteAllText($fixtureEnv, 'ALICIA_AI_PROVIDER=synthetic-user-setting')
    $global:aliciaHarnessUv = Join-Path $fixtureRoot 'uv.ps1'
    $global:aliciaHarnessOllama = Join-Path $fixtureRoot 'ollama.ps1'
    $global:aliciaHarnessShell = (Get-Process -Id $PID).Path
    $fakeBody = @'
$childUv = $null
if ('__TOOL__' -eq 'uv' -and $args -contains '--prepare-audio') {
    # Execute a real child host without the parent's Get-Command double. On Linux,
    # map Windows' case-insensitive Path spelling to the native PATH variable.
    $childUv = & $global:aliciaHarnessShell -NoLogo -NoProfile -NonInteractive -Command 'if ($env:Path) { $env:PATH = $env:Path }; (Get-Command uv.ps1 -CommandType ExternalScript -ErrorAction Stop).Source' 2>$null
}
$global:aliciaHarnessCalls.Add([pscustomobject]@{
    Tool = '__TOOL__'
    Arguments = @($args)
    AiProvider = $env:ALICIA_AI_PROVIDER
    TtsProvider = $env:ALICIA_TTS_PROVIDER
    SttProvider = $env:ALICIA_STT_PROVIDER
    WhisperDevice = $env:ALICIA_WHISPER_DEVICE
    Model = $env:ALICIA_OLLAMA_MODEL
    Url = $env:ALICIA_OLLAMA_URL
    OllamaHost = $env:OLLAMA_HOST
    NoCloud = $env:OLLAMA_NO_CLOUD
    CommandPath = $env:Path
    ChildUv = $childUv
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
    Assert-That ($voicePreparations[0].AiProvider -eq 'ollama' -and $voicePreparations[0].TtsProvider -eq 'chatterbox' -and $voicePreparations[0].SttProvider -eq 'whisper') 'Setup prepares the intended free providers despite old environment values'
    Assert-That ($voicePreparations[0].WhisperDevice -eq 'auto') 'Setup enables automatic recognition device selection'
    Assert-That (($voicePreparations[0].CommandPath -split [IO.Path]::PathSeparator)[0] -eq (Split-Path -Parent $global:aliciaHarnessUv)) 'Setup puts the resolved uv directory first in the child PATH'
    Assert-That ($voicePreparations[0].ChildUv -eq $global:aliciaHarnessUv) 'A real child process can discover the resolved uv fixture through PATH'
    Assert-That ($global:aliciaHarnessShortcuts.Count -eq 1) 'Setup creates the desktop shortcut after successful audio preparation'
    $shortcut = $global:aliciaHarnessShortcuts[0]
    Assert-That ($shortcut.TargetPath -eq 'C:\Windows\System32\wscript.exe') 'Desktop shortcut starts the windowless Windows script host'
    Assert-That ($shortcut.Arguments -eq ('"' + (Join-Path $fixtureRoot 'Lancer_Alicia.vbs') + '"')) 'Shortcut preserves spaces and accents in the quoted launcher path'
    Assert-That ($shortcut.IconLocation -eq ((Join-Path $fixtureRoot 'src/alicia/assets/alicia.ico') + ',0')) 'Shortcut uses the packaged Alicia icon'
    Assert-EnvironmentRestored

    Reset-Fixture
    $global:aliciaHarnessModelPresent = $false
    & (Join-Path $fixtureScripts 'setup_local.ps1') 3>$null 6>$null
    $pulls = @($global:aliciaHarnessCalls | Where-Object { $_.Arguments[0] -eq 'pull' })
    Assert-That ($pulls.Count -eq 1) 'Setup pulls a missing model exactly once'
    Assert-That (($pulls[0].Arguments -join ' ') -eq 'pull qwen3-vl:8b') 'Setup pulls the documented model'
    Assert-That ($pulls[0].OllamaHost -eq 'http://127.0.0.1:11434') 'Pull uses the local Ollama server'
    Assert-That ($pulls[0].NoCloud -eq '1') 'Cloud features disabled for explicit pull process'
    Assert-EnvironmentRestored

    Reset-Fixture
    & (Join-Path $fixtureScripts 'start_alicia.ps1') 3>$null 6>$null
    Assert-That ($global:aliciaHarnessCalls.Count -eq 1) 'Launch invokes only uv'
    $launch = $global:aliciaHarnessCalls[0]
    Assert-That ($launch.Tool -eq 'uv' -and ($launch.Arguments -join ' ') -eq 'run --frozen alicia') 'Launch command preserved'
    Assert-That ($launch.AiProvider -eq 'ollama' -and $launch.TtsProvider -eq 'chatterbox' -and $launch.SttProvider -eq 'whisper') 'Launch forces free local vision, expressive voice and recognition'
    Assert-That ($launch.WhisperDevice -eq 'auto') 'Launch selects the available recognition device automatically'
    Assert-That ($launch.Model -eq 'qwen3-vl:8b') 'Launch uses checked model'
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
    Assert-That ($global:aliciaHarnessShortcuts.Count -eq 0) 'Failed installation does not create a misleading desktop shortcut'
    Assert-EnvironmentRestored

    Reset-Fixture
    & (Join-Path $fixtureScripts 'start_alicia.ps1') -Windowless 3>$null 6>$null
    Assert-That ($global:aliciaHarnessCalls.Count -eq 0) 'Windowless launch does not invoke uv or install packages'
    Assert-That ($global:aliciaHarnessProcesses.Count -eq 1) 'Windowless launch starts one application process'
    $process = $global:aliciaHarnessProcesses[0]
    Assert-That ($process.FilePath -eq $pythonExecutable) 'Windowless launch uses the installed pythonw executable'
    Assert-That (($process.Arguments -join ' ') -eq '-m alicia') 'Windowless process launches the application module'
    Assert-That ($process.WorkingDirectory -eq $fixtureRoot) 'Windowless process preserves project paths with spaces and accents'
    Assert-That ($process.WindowStyle -eq 'Normal' -and $process.Wait -and $process.PassThru) 'pythonw receives a normal GUI startup style while retaining no console'
    Assert-That ($process.TtsProvider -eq 'chatterbox' -and $process.WhisperDevice -eq 'auto') 'Windowless process inherits the free updated audio settings'
    Assert-EnvironmentRestored

    Reset-Fixture
    $global:aliciaHarnessServerReady = $false
    & (Join-Path $fixtureScripts 'start_alicia.ps1') -Windowless 3>$null 6>$null
    Assert-That ($global:aliciaHarnessServerStarts.Count -eq 1) 'A missing local server is started once'
    Assert-That ($global:aliciaHarnessServerStarts[0].WindowStyle -eq 'Hidden') 'The Ollama background server keeps its hidden window style'
    Assert-That ($global:aliciaHarnessProcesses[0].WindowStyle -eq 'Normal') 'The GUI stays visible when launched after a hidden Ollama server'
    Assert-EnvironmentRestored

    Reset-Fixture
    & (Join-Path $fixtureScripts 'start_alicia.ps1') -Windowless -Demo 3>$null 6>$null
    Assert-That (($global:aliciaHarnessProcesses[0].Arguments -join ' ') -eq '-m alicia --demo') 'Windowless demo forwards the demo switch'
    Assert-EnvironmentRestored

    Reset-Fixture
    $global:aliciaHarnessProcessExitCode = 2
    $applicationFailed = $false
    try {
        & (Join-Path $fixtureScripts 'start_alicia.ps1') -Windowless 3>$null 6>$null
    } catch {
        $applicationFailed = $_.Exception.Message -match 'Lancer_Alicia_Debug'
    }
    Assert-That $applicationFailed 'Nonzero pythonw exit becomes a launcher error for the outer dialog'
    Assert-EnvironmentRestored

    Reset-Fixture
    Remove-Item -LiteralPath $pythonExecutable
    $pythonMissingFailed = $false
    try {
        & (Join-Path $fixtureScripts 'start_alicia.ps1') -Windowless 3>$null 6>$null
    } catch {
        $pythonMissingFailed = $_.Exception.Message -match 'Installer_Alicia'
    }
    Assert-That $pythonMissingFailed 'Missing installed interpreter directs the user to the installer'
    Assert-That ($global:aliciaHarnessProcesses.Count -eq 0 -and $global:aliciaHarnessCalls.Count -eq 0) 'Missing interpreter never triggers a download'
    Assert-EnvironmentRestored

    Write-Host "Launcher harness passed: 11 scenarios, $script:assertions assertions; no network, native speech or installed tools used."
} finally {
    $env:Path = $originalCommandPath
    foreach ($name in $trackedVariables) {
        [Environment]::SetEnvironmentVariable($name, $originalVariables[$name], 'Process')
    }
    if (Test-Path -LiteralPath $fixtureRoot) { Remove-Item -LiteralPath $fixtureRoot -Recurse -Force }
    Remove-Variable -Name aliciaHarnessCalls, aliciaHarnessRequests, aliciaHarnessModelPresent, aliciaHarnessPrepareVoiceFails, aliciaHarnessUv, aliciaHarnessOllama, aliciaHarnessProcessExitCode, aliciaHarnessProcesses, aliciaHarnessShortcuts, aliciaHarnessDesktop, aliciaHarnessShell, aliciaHarnessServerReady, aliciaHarnessServerStarts -Scope Global -ErrorAction SilentlyContinue
}
