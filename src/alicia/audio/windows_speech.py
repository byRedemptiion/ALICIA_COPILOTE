"""Offline French feminine speech using voices installed with Windows."""

from __future__ import annotations

import base64
import binascii
import json
import math
import os
import subprocess
import sys
from pathlib import Path

from alicia.audio.ports import SpeechError

# User text is carried only through UTF-8 stdin, never interpolated into this script.
_SPEECH_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$synth = $null
$memory = $null
$encoded = $null
$status = 0
try {
    Add-Type -AssemblyName System.Speech
    $payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $voices = @($synth.GetInstalledVoices() | Where-Object {
        $_.Enabled -and
        $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq 'fr' -and
        $_.VoiceInfo.Gender.ToString() -eq 'Female'
    })
    if ($voices.Count -eq 0) {
        throw [InvalidOperationException]::new('ALICIA_NO_FRENCH_FEMALE_VOICE')
    }
    if ([string]::IsNullOrWhiteSpace([string]$payload.voice)) {
        $chosen = $voices | Where-Object {
            $_.VoiceInfo.Name -eq 'Microsoft Hortense Desktop'
        } | Select-Object -First 1
        if ($null -eq $chosen) { $chosen = $voices[0] }
    } else {
        $chosen = $voices | Where-Object {
            $_.VoiceInfo.Name -eq [string]$payload.voice
        } | Select-Object -First 1
        if ($null -eq $chosen) {
            throw [InvalidOperationException]::new('ALICIA_REQUESTED_VOICE_UNAVAILABLE')
        }
    }
    $synth.SelectVoice($chosen.VoiceInfo.Name)
    $synth.Rate = [int]$payload.rate
    $synth.Volume = 80
    $memory = New-Object System.IO.MemoryStream
    $synth.SetOutputToWaveStream($memory)
    $synth.Speak([string]$payload.text)
    $synth.SetOutputToNull()
    $encoded = [Convert]::ToBase64String($memory.ToArray())
} catch {
    if ($_.Exception.Message -eq 'ALICIA_NO_FRENCH_FEMALE_VOICE') {
        $status = 20
    } elseif ($_.Exception.Message -eq 'ALICIA_REQUESTED_VOICE_UNAVAILABLE') {
        $status = 21
    } else {
        $status = 22
    }
} finally {
    if ($null -ne $synth) { $synth.Dispose() }
    if ($null -ne $memory) { $memory.Dispose() }
}
if ($status -eq 0) { [Console]::Out.Write($encoded) }
exit $status
"""


class WindowsSpeechProvider:
    """Produce WAV bytes locally, without contacting a speech service.

    The Windows voice must be installed and visible to System.Speech; OneCore-only
    voices are not silently substituted. Native synthesis must be validated on Windows.
    """

    def __init__(self, voice_name: str = "", rate: int = -1, timeout_seconds: float = 60) -> None:
        if not isinstance(voice_name, str):
            raise SpeechError("Le nom de la voix Windows doit être du texte.")
        if isinstance(rate, bool) or not isinstance(rate, int) or not -10 <= rate <= 10:
            raise SpeechError("Le débit de voix Windows doit être un entier entre -10 et 10.")
        if not math.isfinite(timeout_seconds) or not 1 <= timeout_seconds <= 300:
            raise SpeechError("Le délai vocal doit être compris entre 1 et 300 secondes.")
        self.voice_name = voice_name.strip()
        self.rate = rate
        self.timeout_seconds = timeout_seconds

    def synthesize(self, text: str) -> bytes:
        if not isinstance(text, str) or not text.strip():
            raise SpeechError("Aucun texte à lire.")
        if len(text) > 4096:
            raise SpeechError("La réponse dépasse 4 096 caractères ; réduisez le texte à lire.")
        if sys.platform != "win32":
            raise SpeechError("La voix locale Windows nécessite Windows.")
        windows_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        powershell = windows_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        command = [
            str(powershell),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            _SPEECH_SCRIPT,
        ]
        payload = json.dumps(
            {"text": text, "voice": self.voice_name, "rate": self.rate}, ensure_ascii=False
        )
        try:
            result = subprocess.run(
                command,
                input=payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                timeout=self.timeout_seconds,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            raise SpeechError("Le délai de génération de la voix Windows est dépassé.") from None
        except (OSError, UnicodeError, subprocess.SubprocessError):
            raise SpeechError(
                "La voix Windows est indisponible. Vérifiez Windows PowerShell et System.Speech."
            ) from None
        if result.returncode == 20:
            raise SpeechError(
                "Aucune voix française féminine compatible n’est installée. "
                "Ajoutez une voix française dans les paramètres de langue et de voix de Windows."
            )
        if result.returncode == 21:
            raise SpeechError(
                "La voix demandée n’est pas disponible parmi les voix françaises féminines Windows."
            )
        if result.returncode != 0:
            raise SpeechError(
                "La génération vocale locale a échoué. Vérifiez les voix installées et System.Speech."
            )
        try:
            audio = base64.b64decode(result.stdout.strip(), validate=True)
        except (ValueError, binascii.Error):
            raise SpeechError("La voix Windows n’a pas produit de fichier WAV valide.") from None
        if len(audio) < 12 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
            raise SpeechError("La voix Windows n’a pas produit de fichier WAV valide.")
        return audio
