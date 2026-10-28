from dataclasses import replace

import pytest

from alicia.__main__ import main
from alicia.audio.ports import SpeechError
from alicia.config import Settings
from alicia.resources import VOICE_REFERENCE


@pytest.fixture
def preparation(monkeypatch, tmp_path):
    settings = replace(
        Settings(),
        expressive_model_directory=tmp_path / "expressive-model",
        expressive_runtime_directory=tmp_path / "expressive-runtime",
        whisper_model_path=tmp_path / "recognition",
        neural_model_directory=tmp_path / "kokoro",
        expressive_device="cpu",
    )
    monkeypatch.setattr("alicia.config.load_settings", lambda: settings)
    calls = []
    monkeypatch.setattr(
        "alicia.audio.chatterbox_setup.prepare_expressive_voice",
        lambda *args, **kwargs: calls.append(("expressive", args, kwargs)),
    )
    monkeypatch.setattr(
        "alicia.audio.neural_setup.prepare_neural_voice",
        lambda path: calls.append(("kokoro", path)),
    )
    monkeypatch.setattr(
        "alicia.audio.whisper_setup.prepare_whisper_model",
        lambda path: calls.append(("recognition", path)),
    )
    return settings, calls


def test_audio_installer_selects_expressive_runtime_and_device(preparation):
    settings, calls = preparation
    assert main(["--prepare-audio"]) == 0
    assert calls == [
        (
            "expressive",
            (settings.expressive_runtime_directory, settings.expressive_model_directory),
            {"reference_audio": VOICE_REFERENCE, "device": "cpu"},
        ),
        ("recognition", settings.whisper_model_path),
    ]


def test_voice_only_command_never_downloads_recognition(preparation):
    _settings, calls = preparation
    assert main(["--prepare-expressive-voice"]) == 0
    assert [call[0] for call in calls] == ["expressive"]


def test_explicit_lightweight_install_does_not_install_heavy_voice(preparation, monkeypatch):
    settings, calls = preparation
    monkeypatch.setattr(
        "alicia.config.load_settings", lambda: replace(settings, tts_provider="kokoro")
    )
    assert main(["--prepare-audio"]) == 0
    assert calls == [
        ("kokoro", settings.neural_model_directory),
        ("recognition", settings.whisper_model_path),
    ]


def test_failed_voice_install_does_not_claim_ready_or_download_next_model(
    preparation, monkeypatch, capsys
):
    _settings, calls = preparation

    def unavailable(*args, **kwargs):
        raise SpeechError("Modèle indisponible.")

    monkeypatch.setattr("alicia.audio.chatterbox_setup.prepare_expressive_voice", unavailable)
    assert main(["--prepare-audio"]) == 2
    output = capsys.readouterr()
    assert "indisponible" in output.err
    assert "prêts" not in output.out
    assert calls == []


def test_demo_never_combines_with_explicit_download(preparation):
    _settings, calls = preparation
    with pytest.raises(SystemExit) as error:
        main(["--prepare-audio", "--demo"])
    assert error.value.code == 2
    assert calls == []
