import base64
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from alicia.audio import windows_speech
from alicia.audio.openai_speech import SpeechError
from alicia.audio.windows_speech import WindowsSpeechProvider

WAV = b"RIFF\x04\x00\x00\x00WAVE"


@pytest.fixture
def run_windows(monkeypatch):
    monkeypatch.setattr(windows_speech.sys, "platform", "win32")
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    run = Mock(
        return_value=SimpleNamespace(returncode=0, stdout=base64.b64encode(WAV).decode(), stderr="")
    )
    monkeypatch.setattr(windows_speech.subprocess, "run", run)
    return run


def test_local_voice_uses_stdin_and_no_shell(run_windows):
    text = "Bonjour, c’est Alicia. $(ne-pas-executer) ; 'é'"
    voice = "Voix française 'locale'"
    assert WindowsSpeechProvider(voice_name=voice).synthesize(text) == WAV
    args, kwargs = run_windows.call_args
    command = args[0]
    assert command[0].endswith("WindowsPowerShell/v1.0/powershell.exe")
    assert text not in " ".join(command)
    assert voice not in " ".join(command)
    assert json.loads(kwargs["input"]) == {"text": text, "voice": voice, "rate": -1}
    assert kwargs.get("shell", False) is False
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["timeout"] == 60
    assert "-NoProfile" in command and "-NonInteractive" in command


def test_selection_is_french_feminine_and_disposes_resources():
    script = windows_speech._SPEECH_SCRIPT
    assert "TwoLetterISOLanguageName -eq 'fr'" in script
    assert "Gender.ToString() -eq 'Female'" in script
    assert "Microsoft Hortense Desktop" in script
    assert "$synth.Volume = 80" in script
    assert "$synth.Dispose()" in script
    assert "$memory.Dispose()" in script
    assert "SetOutputToNull()" in script


@pytest.mark.parametrize("text", ["", " ", "a" * 4097, None])
def test_invalid_text_does_not_spawn(text, run_windows):
    with pytest.raises(SpeechError):
        WindowsSpeechProvider().synthesize(text)
    run_windows.assert_not_called()


def test_non_windows_does_not_spawn(monkeypatch):
    monkeypatch.setattr(windows_speech.sys, "platform", "linux")
    run = Mock()
    monkeypatch.setattr(windows_speech.subprocess, "run", run)
    with pytest.raises(SpeechError, match="nécessite Windows"):
        WindowsSpeechProvider().synthesize("Bonjour")
    run.assert_not_called()


@pytest.mark.parametrize(
    "code, message",
    [(20, "voix française féminine"), (21, "voix demandée"), (22, "locale a échoué")],
)
def test_native_errors_are_sanitized(code, message, run_windows):
    run_windows.return_value = SimpleNamespace(
        returncode=code, stdout="private user text", stderr="private user text"
    )
    with pytest.raises(SpeechError, match=message) as error:
        WindowsSpeechProvider().synthesize("private user text")
    assert "private user text" not in str(error.value)


def test_timeout_is_sanitized(run_windows):
    run_windows.side_effect = subprocess.TimeoutExpired("private user text", 2)
    with pytest.raises(SpeechError, match="délai") as error:
        WindowsSpeechProvider(timeout_seconds=2).synthesize("private user text")
    assert "private" not in str(error.value)


def test_missing_powershell_is_sanitized(run_windows):
    run_windows.side_effect = FileNotFoundError("private file path")
    with pytest.raises(SpeechError, match="indisponible") as error:
        WindowsSpeechProvider().synthesize("Bonjour")
    assert "private" not in str(error.value)


@pytest.mark.parametrize("output", ["%%%", "", base64.b64encode(b"not a wav").decode()])
def test_invalid_output_is_rejected(output, run_windows):
    run_windows.return_value.stdout = output
    with pytest.raises(SpeechError, match="WAV"):
        WindowsSpeechProvider().synthesize("Bonjour")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"rate": -11},
        {"rate": 11},
        {"rate": True},
        {"rate": -1.5},
        {"timeout_seconds": 0},
        {"timeout_seconds": float("inf")},
        {"voice_name": None},
    ],
)
def test_invalid_settings(kwargs):
    with pytest.raises(SpeechError):
        WindowsSpeechProvider(**kwargs)
