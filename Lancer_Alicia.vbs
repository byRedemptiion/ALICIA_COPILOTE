Option Explicit

Dim shell, fileSystem, projectRoot, scriptPath, powershellPath, command, exitCode
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")
projectRoot = fileSystem.GetParentFolderName(WScript.ScriptFullName)
scriptPath = fileSystem.BuildPath(projectRoot, "scripts\start_alicia.ps1")
powershellPath = shell.ExpandEnvironmentStrings("%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe")

If Not fileSystem.FileExists(scriptPath) Then
    shell.Popup "Le dossier Alicia est incomplet. Extrayez toute l'archive avant de lancer Alicia.", 0, "Alicia", 16
    WScript.Quit 2
End If

command = Quote(powershellPath) & " -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File " & Quote(scriptPath) & " -Windowless"
On Error Resume Next
' Window style 0 hides the launcher; pythonw keeps the application window visible.
exitCode = shell.Run(command, 0, True)
If Err.Number <> 0 Then
    On Error GoTo 0
    shell.Popup "Impossible de lancer Alicia. Utilisez Lancer_Alicia_Debug.bat pour afficher le diagnostic.", 0, "Alicia", 16
    WScript.Quit 2
End If
On Error GoTo 0

If exitCode <> 0 Then
    shell.Popup "Alicia n'a pas pu demarrer ou s'est arretee avec une erreur. Lancez Lancer_Alicia_Debug.bat pour afficher le diagnostic. Si l'installation est incomplete, relancez Installer_Alicia.bat.", 0, "Alicia", 16
End If
WScript.Quit exitCode

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function
