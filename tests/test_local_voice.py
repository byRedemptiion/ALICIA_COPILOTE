import io
import wave

import numpy as np
import pytest

from alicia.app import build_services
from alicia.core.ai.base import PreparedAudio
from alicia.core.ai.providers.fake import FakeModel
from alicia.core.audio.models import kokoro_paths
from alicia.core.audio.speaker import kokoro_synthesizer, make_synthesizer
from alicia.core.audio.stt import _HALLUCINATIONS, wav_to_float
from alicia.core.capture.backends import DEMO_WINDOW
from alicia.core.config import VoiceSettings, load_settings
from alicia.core.errors import AliciaError, ConfigError


def wav(seconds=1.0, rate=16000):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes((np.ones(int(seconds * rate)) * 1000).astype(np.int16).tobytes())
    return PreparedAudio(buffer.getvalue(), "audio/wav", seconds)


class FakeTranscriber:
    def __init__(self, text):
        self.text, self.calls = text, 0

    def transcribe(self, audio):
        self.calls += 1
        return self.text


@pytest.fixture
def settings(tmp_path):
    return load_settings(
        cwd=tmp_path, environ={"ALICE_AI_PROVIDER": "fake"}, user_dir=tmp_path / "u"
    )


def test_local_transcript_is_sent_as_text_not_audio(settings):
    model = FakeModel()
    services = build_services(
        settings, demo=True, model=model, transcriber=FakeTranscriber("quel objet pour Ashe ?")
    )
    seen = []
    outcome = services.analysis.analyze(DEMO_WINDOW, "", audio=wav(), on_transcript=seen.append)
    request = model.requests[-1]
    assert request.audio is None
    assert request.question == "quel objet pour Ashe ?"
    assert seen == ["quel objet pour Ashe ?"]
    assert outcome.transcript == "quel objet pour Ashe ?"
    assert services.session.last.question == "quel objet pour Ashe ?"


def test_empty_transcript_stops_before_calling_ai(settings):
    model = FakeModel()
    services = build_services(settings, demo=True, model=model, transcriber=FakeTranscriber(""))
    with pytest.raises(AliciaError, match="rien compris"):
        services.analysis.analyze(DEMO_WINDOW, "", audio=wav())
    assert model.requests == []


def test_whisper_hallucinations_are_filtered():
    assert _HALLUCINATIONS.search("Sous-titrage réalisé par la communauté d'Amara.org")
    assert _HALLUCINATIONS.search("  ...  ")
    assert not _HALLUCINATIONS.search("Quel objet j'achète pour Ashe ?")


def test_wav_is_converted_for_whisper():
    samples = wav_to_float(wav(0.5))
    assert samples.dtype == np.float32 and len(samples) == 8000
    assert abs(samples[0] - 1000 / 32768) < 1e-6


def test_voice_engine_settings_are_validated(tmp_path):
    (tmp_path / "alicia.toml").write_text('[voice]\ntts_engine = "robot"\n')
    with pytest.raises(ConfigError):
        load_settings(cwd=tmp_path, environ={}, user_dir=tmp_path / "u")
    (tmp_path / "alicia.toml").write_text('[voice]\ntts_engine = "kokoro"\nstt = "gemini"\n')
    voice = load_settings(cwd=tmp_path, environ={}, user_dir=tmp_path / "u").voice
    assert (voice.tts_engine, voice.stt, voice.kokoro_voice) == ("kokoro", "gemini", "ff_siwis")


def test_kokoro_missing_model_gives_install_hint(monkeypatch, tmp_path):
    monkeypatch.setattr("alicia.core.audio.models.models_dir", lambda: tmp_path / "none")
    synth = make_synthesizer(VoiceSettings(tts_engine="kokoro"))
    with pytest.raises(AliciaError, match="prepare-voice"):
        synth("Bonjour à toi.")


@pytest.mark.skipif(not all(p.is_file() for p in kokoro_paths()), reason="modèle Kokoro absent")
def test_kokoro_speaks_french_for_real():
    samples = kokoro_synthesizer("ff_siwis", 1.05)("Bonjour, je suis Alicia.")
    assert samples.dtype == np.int16 and len(samples) > 24000 * 0.8
    assert np.abs(samples).max() > 1000
