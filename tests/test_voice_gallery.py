import base64
import tomllib

import httpx
import numpy as np
import pytest

from alicia.app import build_services
from alicia.core.audio import speaker as speaker_module
from alicia.core.audio.devices import AudioError
from alicia.core.config import Secret, VoiceSettings, data_dir, load_settings


def test_gemini_voice_returns_pcm(monkeypatch):
    sent = {}
    pcm = np.array([0, 1000, -1000, 5], dtype=np.int16).tobytes()

    def post(url, headers, json, timeout):
        sent.update(url=url, headers=headers, json=json)
        body = {
            "candidates": [
                {"content": {"parts": [{"inlineData": {"data": base64.b64encode(pcm).decode()}}]}}
            ]
        }
        return httpx.Response(200, json=body)

    monkeypatch.setattr(httpx, "post", post)
    settings = VoiceSettings(tts_engine="gemini", gemini_voice="Puck", gemini_key=Secret("k"))
    samples = speaker_module.make_synthesizer(settings)("Salut !")
    assert samples.tolist() == [0, 1000, -1000, 5]
    assert (
        "gemini-3.1-flash-tts-preview" in sent["url"] and sent["headers"]["x-goog-api-key"] == "k"
    )
    voice = sent["json"]["generationConfig"]["speechConfig"]["voiceConfig"]
    assert voice["prebuiltVoiceConfig"]["voiceName"] == "Puck"
    assert sent["json"]["contents"][0]["parts"][0]["text"].endswith("Salut !")


def test_gemini_voice_needs_a_key_and_reports_quota(monkeypatch):
    with pytest.raises(AudioError):
        speaker_module.gemini_synthesizer(VoiceSettings())("x")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(429, text="quota"))
    with pytest.raises(AudioError, match="quota"):
        speaker_module.gemini_synthesizer(VoiceSettings(gemini_key=Secret("k")))("x")


class RecordingSpeaker:
    speaking = False
    level = 0.0

    def __init__(self, settings):
        self.settings = settings
        self.synthesizer = object()
        self.player = object()
        self.said = []

    def speak(self, text, synthesizer=None):
        self.said.append((text, synthesizer))
        return True

    def stop(self):
        pass

    def warm_up_async(self):
        pass


def test_gallery_previews_without_choosing_then_chooses(qt_app, tmp_path, monkeypatch):
    from alicia.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    settings = load_settings(environ={"ALICE_AI_PROVIDER": "fake"})
    speaker = RecordingSpeaker(settings.voice)
    window = MainWindow(build_services(settings, demo=True, speaker=speaker))
    try:
        page = window.settings_page
        assert len(page.gallery_buttons) == 13 + 30
        before = window.services.settings.voice.tts_engine
        window.change_setting("voice_preview", "edge|fr-FR-EloiseNeural")
        assert speaker.said and callable(speaker.said[-1][1])  # voix d'essai, pas la sienne
        assert window.services.settings.voice.tts_engine == before  # rien n'est changé

        window.change_setting("voice_choose", "gemini|Leda")
        voice = window.services.settings.voice
        assert voice.tts_engine == "gemini" and voice.gemini_voice == "Leda"
        assert page.gallery_buttons["gemini|Leda"].text() == "✓ Choisie"
        saved = tomllib.loads((data_dir() / "alicia.toml").read_text("utf-8"))
        assert saved["voice"]["tts_engine"] == "gemini" and saved["voice"]["gemini_voice"] == "Leda"

        window.change_setting("voice_choose", "edge|fr-FR-HenriNeural")
        assert window.services.settings.voice.tts_voice == "fr-FR-HenriNeural"
        assert page.gallery_buttons["gemini|Leda"].text() == "Choisir"
    finally:
        window.close()
