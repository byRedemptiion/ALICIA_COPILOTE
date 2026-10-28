import io
import wave
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from alicia.audio.kokoro_speech import KokoroSpeechProvider, KokoroSpeechSettings
from alicia.audio.ports import SpeechError


def engine(samples=None, rate=24000):
    samples = [0.0, 0.5, -0.5, 1.2, -1.2] if samples is None else samples
    return SimpleNamespace(create=Mock(return_value=(samples, rate)))


def test_natural_voice_returns_pcm_wav_and_uses_french_feminine_voice(tmp_path):
    fake = engine()
    provider = KokoroSpeechProvider(KokoroSpeechSettings(tmp_path), fake)
    output = provider.synthesize(" Bonjour Alicia. ")
    fake.create.assert_called_once_with(
        "Bonjour Alicia.", voice="ff_siwis", speed=0.95, lang="fr-fr"
    )
    with wave.open(io.BytesIO(output), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 24000
        assert audio.getnframes() == 5
        assert audio.readframes(5) == b"\x00\x00\xff\x3f\x01\xc0\xff\x7f\x01\x80"


@pytest.mark.parametrize("text", ["", " ", None, "x" * 4097])
def test_empty_or_long_text_is_rejected_before_engine_call(tmp_path, text):
    fake = engine()
    with pytest.raises(SpeechError):
        KokoroSpeechProvider(KokoroSpeechSettings(tmp_path), fake).synthesize(text)
    fake.create.assert_not_called()


@pytest.mark.parametrize("voice", ["af_sarah", "fm_test", "ff_siwis; command", "", None])
def test_only_french_feminine_voice_names_are_accepted(tmp_path, voice):
    with pytest.raises(SpeechError, match="féminine"):
        KokoroSpeechProvider(KokoroSpeechSettings(tmp_path, voice=voice))


@pytest.mark.parametrize("speed", [0.6, 1.4, float("nan"), float("inf"), True, None, "bad"])
def test_invalid_speed_is_rejected(tmp_path, speed):
    with pytest.raises(SpeechError, match="vitesse"):
        KokoroSpeechProvider(KokoroSpeechSettings(tmp_path, speed=speed))


def test_constructor_does_not_load_model_or_download(tmp_path, monkeypatch):
    load = Mock(side_effect=AssertionError("The constructor must stay lazy"))
    monkeypatch.setattr(KokoroSpeechProvider, "_load_engine", load)
    KokoroSpeechProvider(KokoroSpeechSettings(tmp_path))
    load.assert_not_called()


def test_missing_model_is_an_explicit_setup_error_without_paid_fallback(tmp_path):
    with pytest.raises(SpeechError, match="Installer_Alicia"):
        KokoroSpeechProvider(KokoroSpeechSettings(tmp_path)).synthesize("Bonjour.")


def test_engine_is_cached_after_first_load(tmp_path, monkeypatch):
    fake = engine()
    load = Mock(return_value=fake)
    monkeypatch.setattr(KokoroSpeechProvider, "_load_engine", load)
    provider = KokoroSpeechProvider(KokoroSpeechSettings(tmp_path))
    provider.synthesize("Bonjour.")
    provider.synthesize("Au revoir.")
    load.assert_called_once()
    assert fake.create.call_count == 2


def test_model_errors_do_not_expose_text_or_engine_details(tmp_path):
    fake = engine()
    fake.create.side_effect = RuntimeError("private question and engine dump")
    with pytest.raises(SpeechError) as error:
        KokoroSpeechProvider(KokoroSpeechSettings(tmp_path), fake).synthesize("private text")
    assert "private" not in str(error.value)


@pytest.mark.parametrize(
    "samples,rate",
    [
        ([], 24000),
        ([[0.0]], 24000),
        ([float("nan")], 24000),
        ([float("inf")], 24000),
        ([0.0], 0),
        ([0.0], True),
        ([0.0], 24000.0),
    ],
)
def test_invalid_engine_audio_is_not_reported_as_success(tmp_path, samples, rate):
    with pytest.raises(SpeechError):
        KokoroSpeechProvider(KokoroSpeechSettings(tmp_path), engine(samples, rate)).synthesize(
            "Bonjour."
        )
