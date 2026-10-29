import logging

import pytest

from alice.app import build_services
from alice.core.ai.providers.fake import FakeModel
from alice.core.capture.backends import DEMO_WINDOW
from alice.core.capture.models import WindowInfo
from alice.core.config import load_settings
from alice.core.errors import ProviderError, ProviderErrorKind
from alice.core.logging_setup import setup_logging
from alice.games.profiles import resolve_profile


@pytest.fixture
def settings(tmp_path):
    # Pas de vraie voix ni de vrai micro dans les tests : doubles injectés au besoin.
    (tmp_path / "alice.toml").write_text("[voice]\nspeak_answers = false\n", encoding="utf-8")
    return load_settings(
        cwd=tmp_path, environ={"ALICE_AI_PROVIDER": "fake"}, user_dir=tmp_path / "u"
    )


def test_analysis_uses_capture_history_and_profile(settings):
    model = FakeModel()
    services = build_services(settings, demo=True, model=model)
    deltas, frames = [], []
    first = services.analysis.analyze(
        DEMO_WINDOW, "Quel objet ?", on_delta=deltas.append, on_frame=frames.append
    )
    assert "Image reçue : 1280x720" in first.result.text
    assert "".join(deltas) == first.result.text
    assert frames and frames[0].backend == "demo"

    services.analysis.analyze(DEMO_WINDOW, "Et le deuxième ?")
    second_request = model.requests[-1]
    assert second_request.history[0].question == "Quel objet ?"
    assert second_request.images[0].mime_type == "image/jpeg"


def test_empty_question_gets_a_default(settings):
    model = FakeModel()
    services = build_services(settings, demo=True, model=model)
    services.analysis.analyze(DEMO_WINDOW, "   ")
    assert model.requests[0].question


def test_overwatch_profile_is_detected():
    window = WindowInfo(1, "Overwatch", 2, exe_name="Overwatch.exe")
    profile = resolve_profile(window)
    assert profile.key == "overwatch"
    assert "Stadium" in profile.context
    assert resolve_profile(DEMO_WINDOW).key == "generic"
    assert resolve_profile(window, "generic").key == "generic"


def test_logs_are_written_with_operation_id(settings, tmp_path):
    log_file = setup_logging(tmp_path / "logs", "INFO", console=False)
    services = build_services(settings, demo=True, model=FakeModel())
    outcome = services.analysis.analyze(DEMO_WINDOW, "Quel objet ?")
    for handler in logging.getLogger("alice").handlers:
        handler.flush()
    text = log_file.read_text(encoding="utf-8")
    assert f"[{outcome.operation_id}] Capture ok via demo" in text
    assert "Appel IA fake/fake-1" in text
    assert "Quel objet ?" not in text  # question visible seulement en DEBUG


@pytest.fixture
def qt_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def run_until(app, window, timeout_ms=5000):
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    result = {}
    window.analysis_done.connect(lambda value: (result.setdefault("value", value), loop.quit()))
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    return result.get("value")


def test_ui_full_flow_streams_answer(qt_app, settings):
    from alice.ui.main_window import MainWindow

    window = MainWindow(build_services(settings, demo=True, model=FakeModel()))
    window.window_list.setCurrentRow(0)
    window.question.setText("Quel objet ?")
    window.analyze_or_cancel()
    assert window.busy and window.analyze_button.text() == "Annuler"
    outcome = run_until(qt_app, window)
    assert not isinstance(outcome, Exception)
    assert "Image reçue" in window.answer.toPlainText()
    assert "demo" in window.preview_info.text()
    assert window.analyze_button.text() == "Analyser"
    window.close()


def test_ui_shows_provider_error_clearly(qt_app, settings):
    from alice.ui.main_window import MainWindow

    failing = FakeModel(
        fail_with=ProviderError(ProviderErrorKind.RATE_LIMIT, "Quota Gemini atteint.")
    )
    window = MainWindow(build_services(settings, demo=True, model=failing))
    window.window_list.setCurrentRow(0)
    window.analyze_or_cancel()
    run_until(qt_app, window)
    assert "Quota Gemini atteint." in window.status.text()
    assert not window.busy
    window.close()


def test_ui_stop_discards_late_result(qt_app, settings):
    from PySide6.QtCore import QEventLoop, QThreadPool, QTimer

    from alice.ui.main_window import MainWindow

    window = MainWindow(build_services(settings, demo=True, model=FakeModel(delay_s=0.05)))
    window.window_list.setCurrentRow(0)
    window.analyze_or_cancel()
    window.stop_observation()
    QThreadPool.globalInstance().waitForDone(5000)
    loop = QEventLoop()
    QTimer.singleShot(100, loop.quit)
    loop.exec()
    assert window.answer.toPlainText() in ("",) or "Image reçue" not in window.answer.toPlainText()
    assert window.start_button.text() == "Démarrer"
    window.close()


def test_parse_hotkey():
    from alice.core.errors import ConfigError
    from alice.ui.hotkey import MOD_ALT, MOD_CONTROL, MOD_SHIFT, parse_hotkey

    assert parse_hotkey("F9") == (0, 0x78)
    assert parse_hotkey("ctrl+F9") == (MOD_CONTROL, 0x78)
    assert parse_hotkey("Alt + Shift + a") == (MOD_ALT | MOD_SHIFT, ord("A"))
    for bad in ("", "hyper+F9", "F99", "ctrl+Entrée"):
        with pytest.raises(ConfigError):
            parse_hotkey(bad)


def test_hotkey_analyzes_observed_window_with_default_question(qt_app, settings):
    from alice.ui.main_window import DEFAULT_HOTKEY_QUESTION, MainWindow

    model = FakeModel()
    window = MainWindow(build_services(settings, demo=True, model=model))
    window.hotkey_analyze()  # aucune fenêtre active ni choisie
    assert "premier plan" in window.status.text()
    window.window_list.setCurrentRow(0)
    window.start_observation()
    window.hotkey_analyze()
    outcome = run_until(qt_app, window)
    assert not isinstance(outcome, Exception)
    assert model.requests[-1].question == DEFAULT_HOTKEY_QUESTION
    window.close()


def test_minimized_window_error_points_to_hotkey(tmp_path):
    from alice.core.capture.service import CaptureService
    from alice.core.errors import CaptureError

    def refuse(window):
        raise CaptureError("La fenêtre du jeu est réduite … F9", detail="IsIconic")

    service = CaptureService(lambda: [], refuse, lambda w: [])
    with pytest.raises(CaptureError) as info:
        service.capture(DEMO_WINDOW)
    assert "F9" in info.value.user_message


class FakeRecorder:
    def __init__(self, audio=None, error=None):
        self.audio, self.error, self.recording, self.started = audio, error, False, 0

    def start(self):
        self.recording, self.started = True, self.started + 1

    def stop(self):
        self.recording = False
        if self.error:
            raise self.error
        return self.audio

    def cancel(self):
        self.recording = False


class FakeSpeaker:
    def __init__(self):
        self.spoken, self.stopped, self.speaking = [], 0, False
        self.on_state = lambda state, msg: None

    def speak(self, text):
        self.spoken.append(text)
        return True

    def stop(self):
        self.stopped += 1


def test_voice_question_transcript_is_shown_and_answer_spoken(qt_app, settings):
    from alice.core.ai.base import PreparedAudio
    from alice.ui.main_window import MainWindow

    audio = PreparedAudio(b"RIFF....", "audio/wav", 2.5)
    recorder, speaker, model = FakeRecorder(audio), FakeSpeaker(), FakeModel()
    services = build_services(settings, demo=True, model=model, speaker=speaker, recorder=recorder)
    window = MainWindow(services)
    window.voice_box.setChecked(True)
    window.window_list.setCurrentRow(0)
    window.start_observation()
    window.talk_pressed()
    assert recorder.recording and "écoute" in window.status.text()
    window.talk_released()
    outcome = run_until(qt_app, window)
    assert not isinstance(outcome, Exception)
    assert outcome.transcript == "question orale factice"
    assert window.question.text() == "🎙 question orale factice"
    assert not window.answer.toPlainText().startswith("Question :")
    assert model.requests[-1].audio is audio
    assert speaker.spoken and "Réponse factice" in speaker.spoken[0]
    assert services.session.last.question == "question orale factice"
    window.close()


def test_silent_microphone_is_reported_without_calling_ai(qt_app, settings):
    from alice.core.audio.devices import AudioError
    from alice.ui.main_window import MainWindow

    recorder = FakeRecorder(error=AudioError("Aucun son capté par le micro « X »."))
    model = FakeModel()
    window = MainWindow(build_services(settings, demo=True, model=model, recorder=recorder))
    window.window_list.setCurrentRow(0)
    window.start_observation()
    window.talk_pressed()
    window.talk_released()
    assert "Aucun son" in window.status.text()
    assert model.requests == []
    window.close()


def test_talking_interrupts_alice(qt_app, settings):
    from alice.ui.main_window import MainWindow

    speaker = FakeSpeaker()
    speaker.speaking = True
    window = MainWindow(
        build_services(
            settings, demo=True, model=FakeModel(), speaker=speaker, recorder=FakeRecorder()
        )
    )
    window.talk_pressed()
    assert speaker.stopped >= 1
    window.close()


def test_web_search_flag_and_sources_reach_the_ui(qt_app, settings):
    from alice.core.ai.base import Source
    from alice.ui.main_window import MainWindow

    class SourcedModel(FakeModel):
        def analyze(self, request, on_delta=None, cancel=None):
            result = super().analyze(request, on_delta, cancel)
            result.sources = [Source("Guide Stadium", "https://example.com/stadium")]
            return result

    model = SourcedModel()
    window = MainWindow(build_services(settings, demo=True, model=model))
    window.web_box.setChecked(True)
    window.window_list.setCurrentRow(0)
    window.analyze_or_cancel()
    run_until(qt_app, window)
    assert model.requests[-1].web_search is True
    assert "Guide Stadium" in window.sources_label.text()
    window.close()
