from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from alicia.capture.demo import DemoCapture
from alicia.config import Settings
from alicia.core.models import AnalysisResult, WebSource
from alicia.research.search import SearchError
from alicia.ui.main_window import MainWindow
from alicia.ui.smoke import wait_until


class FakeListener:
    def __init__(self, model_path, on_text, on_error, on_activity, on_partial=None):
        self.model_path = model_path
        self.on_text = on_text
        self.on_error = on_error
        self.on_activity = on_activity
        self.on_partial = on_partial
        self.active = False
        self.paused = False
        self.pause_count = 0

    def start(self, _device=None):
        self.active = True
        self.paused = False
        self.on_activity(True)

    def pause(self):
        self.paused = True
        self.pause_count += 1

    def resume(self):
        self.paused = False

    def stop(self):
        self.active = False
        self.paused = True
        self.on_activity(False)


class CountingCapture(DemoCapture):
    def __init__(self):
        self.count = 0

    def capture(self, window):
        self.count += 1
        return super().capture(window)


class FakeVision:
    def __init__(self):
        self.requests = []

    def analyze(self, request):
        self.requests.append(request)
        return AnalysisResult(
            "Réponse de test avec source [1].",
            "fake-test",
            0.1,
            request.frame.capture_id,
            request.web_sources,
        )


class FakeSearch:
    def __init__(self):
        self.queries = []
        self.error = None
        self.started = Event()
        self.release = Event()
        self.release.set()
        self.sources = (
            WebSource(
                "Notes de mise à jour",
                "https://example.org/patch",
                "Extrait récent.",
                datetime(2026, 10, 28, tzinfo=UTC),
            ),
        )

    def search(self, question):
        self.queries.append(question)
        self.started.set()
        if not self.release.wait(timeout=3):
            raise SearchError("Délai du serveur de test")
        if self.error is not None:
            raise self.error
        return self.sources


@pytest.fixture
def conversation_window(app, tmp_path, monkeypatch):
    capture = CountingCapture()
    vision = FakeVision()
    window = MainWindow(
        Settings(log_directory=tmp_path, capture_interval_ms=10000),
        capture,
        vision,
        demo=True,
    )
    window.show()
    wait_until(app, lambda: not window.jobs)
    window.conversation.continuous.setChecked(False)
    listeners = []

    def listener_factory(*args, **kwargs):
        listener = FakeListener(*args, **kwargs)
        listeners.append(listener)
        return listener

    window.conversation.listener_factory = listener_factory
    syntheses, audio = [], []

    def synthesize(text):
        syntheses.append(text)
        return b"fake WAV for UI test only"

    def play(payload):
        audio.append(payload)
        window.playback._active = True
        window.playback.speaking_changed.emit(True)

    monkeypatch.setattr(window.speech_provider, "synthesize", synthesize)
    monkeypatch.setattr(window.playback, "play", play)
    search = FakeSearch()
    window.research_provider = search
    fixture = SimpleNamespace(
        window=window,
        app=app,
        capture=capture,
        vision=vision,
        listeners=listeners,
        syntheses=syntheses,
        audio=audio,
        search=search,
    )
    yield fixture
    search.release.set()
    window.stop()
    wait_until(app, lambda: not window.jobs)
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def listen(fixture):
    window = fixture.window
    window.start_button.click()
    window.consent.setChecked(True)
    window.conversation.toggle.click()
    assert fixture.listeners
    assert fixture.listeners[-1].active
    return fixture.listeners[-1]


def finish_audio(fixture):
    fixture.window.playback._active = False
    fixture.window.playback.speaking_changed.emit(False)
    fixture.window.playback.finished.emit()
    wait_until(fixture.app, lambda: not fixture.listeners[-1].paused)


def test_no_microphone_is_opened_by_launch(conversation_window):
    fixture = conversation_window
    assert fixture.listeners == []
    assert fixture.window.conversation.listener is None
    assert fixture.vision.requests == []
    assert fixture.audio == []


def test_ordinary_conversation_without_name_is_ignored(conversation_window):
    fixture = conversation_window
    listener = listen(fixture)
    listener.on_text("Quel objet choisir ?")
    fixture.app.processEvents()
    assert fixture.capture.count == 0
    assert fixture.vision.requests == []
    assert fixture.syntheses == []


def test_wake_question_captures_fresh_frame_and_answers_aloud(conversation_window):
    fixture = conversation_window
    listener = listen(fixture)
    fixture.window.capture(background=True)
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    previous = fixture.window.session.frame
    listener.on_text("Alicia, compare ces objets")
    wait_until(fixture.app, lambda: not fixture.window.jobs and bool(fixture.audio))
    assert fixture.capture.count == 2
    assert len(fixture.vision.requests) == 1
    request = fixture.vision.requests[0]
    assert request.question == "compare ces objets"
    assert request.frame.capture_id != previous.capture_id
    assert fixture.syntheses == ["Réponse de test avec source [1]."]
    assert fixture.window.avatar.state == "speaking"
    assert listener.paused
    finish_audio(fixture)


def test_wake_name_then_next_phrase_is_one_question(conversation_window):
    fixture = conversation_window
    listener = listen(fixture)
    listener.on_text("Alicia")
    assert fixture.window.conversation.gate.armed
    assert fixture.vision.requests == []
    listener.on_text("Quel objet privilégier ?")
    wait_until(fixture.app, lambda: not fixture.window.jobs and bool(fixture.audio))
    assert len(fixture.vision.requests) == 1
    assert fixture.vision.requests[0].question == "Quel objet privilégier ?"


def test_stopping_microphone_invalidates_already_queued_callbacks(conversation_window):
    fixture = conversation_window
    listener = listen(fixture)
    callback = listener.on_text
    fixture.window.conversation.stop_listening()
    callback("Alicia, compare ces objets")
    fixture.app.processEvents()
    assert not listener.active
    assert fixture.capture.count == 0
    assert fixture.vision.requests == []
    assert fixture.syntheses == []


def test_own_voice_and_extra_questions_are_ignored_while_speaking(conversation_window):
    fixture = conversation_window
    listener = listen(fixture)
    listener.on_text("Alicia, explique cet écran")
    wait_until(fixture.app, lambda: not fixture.window.jobs and bool(fixture.audio))
    assert listener.paused
    listener.on_text("Alicia, répète cette réponse")
    fixture.app.processEvents()
    assert len(fixture.vision.requests) == 1
    finish_audio(fixture)
    listener.on_text("Alicia, compare à nouveau")
    wait_until(fixture.app, lambda: not fixture.window.jobs and len(fixture.audio) == 2)
    assert len(fixture.vision.requests) == 2


def test_auto_voice_can_be_disabled(conversation_window):
    fixture = conversation_window
    fixture.window.conversation.auto_voice.setChecked(False)
    listener = listen(fixture)
    listener.on_text("Alicia, explique cet écran")
    wait_until(
        fixture.app, lambda: not fixture.window.jobs and fixture.window.session.result is not None
    )
    assert fixture.syntheses == []
    assert fixture.audio == []
    wait_until(fixture.app, lambda: not listener.paused, timeout=3)


def test_continuous_capture_does_not_call_ai_or_interrupt_listening(conversation_window):
    fixture = conversation_window
    listener = listen(fixture)
    listener.on_text("Alicia")
    assert fixture.window.conversation.gate.armed
    fixture.window.conversation.continuous.setChecked(True)
    fixture.window.conversation._refresh_screen()
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    assert fixture.capture.count == 1
    assert fixture.vision.requests == []
    assert fixture.syntheses == []
    assert listener.active and not listener.paused
    assert fixture.window.conversation.gate.armed
    assert listener.pause_count == 0


def test_web_sends_question_only_and_displays_sources(conversation_window):
    fixture = conversation_window
    fixture.window.conversation.web.setChecked(True)
    listener = listen(fixture)
    listener.on_text("Alicia, quelle est la dernière mise à jour ?")
    wait_until(fixture.app, lambda: not fixture.window.jobs and bool(fixture.audio))
    assert fixture.search.queries == ["quelle est la dernière mise à jour ?"]
    assert fixture.vision.requests[0].web_sources == fixture.search.sources
    assert not fixture.window.sources.isHidden()
    assert "https://example.org/patch" in fixture.window.sources.toHtml()
    assert "Notes de mise à jour" in fixture.window.sources.toPlainText()


def test_failed_search_does_not_fall_back_to_unsourced_answer(conversation_window):
    fixture = conversation_window
    fixture.search.error = SearchError("Recherche refusée par le serveur de test")
    fixture.window.conversation.web.setChecked(True)
    listener = listen(fixture)
    listener.on_text("Alicia, quelle est la dernière mise à jour ?")
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    assert fixture.vision.requests == []
    assert fixture.syntheses == []
    assert fixture.window.session.result is None
    assert fixture.window.conversation.phase == "idle"
    assert not listener.active
    assert fixture.window.conversation.listener is None


def test_revoking_web_during_search_prevents_analysis(conversation_window):
    fixture = conversation_window
    fixture.search.release.clear()
    fixture.window.conversation.web.setChecked(True)
    listener = listen(fixture)
    listener.on_text("Alicia, quelle est la dernière mise à jour ?")
    wait_until(fixture.app, fixture.search.started.is_set)
    fixture.window.conversation.web.setChecked(False)
    fixture.search.release.set()
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    assert fixture.vision.requests == []
    assert fixture.syntheses == []
    assert fixture.window.session.result is None
    assert not listener.active


def test_research_finishing_after_analysis_still_advances_to_speech(conversation_window):
    fixture = conversation_window
    window = fixture.window
    listener = listen(fixture)
    window.capture(background=True)
    wait_until(fixture.app, lambda: not window.jobs)
    window.session.result = AnalysisResult(
        "Réponse déjà reçue pendant la recherche.",
        "fake-test",
        0.1,
        window.session.frame.capture_id,
    )
    window.conversation.phase = "analyzing"
    window.conversation.generation = window.session.generation
    window.conversation.question = "Question de test"
    window.conversation.pause()
    window.jobs.add("research")
    window._finished("research")
    wait_until(fixture.app, lambda: not window.jobs and bool(fixture.audio))
    assert fixture.syntheses == ["Réponse déjà reçue pendant la recherche."]
    assert window.conversation.phase == "speaking"
    assert listener.paused


def test_end_of_playback_keeps_short_echo_cooldown_despite_job_completion(conversation_window):
    fixture = conversation_window
    listener = listen(fixture)
    listener.on_text("Alicia, explique cet écran")
    wait_until(fixture.app, lambda: not fixture.window.jobs and bool(fixture.audio))
    fixture.window.playback._active = False
    fixture.window.playback.speaking_changed.emit(False)
    fixture.window.playback.finished.emit()
    fixture.window.conversation.job_finished("speech")
    assert listener.paused
    fixture.window.conversation.resume_if_idle()
    assert listener.paused
    listener.on_text("Alicia, phrase provenant de la fin de lecture")
    assert len(fixture.vision.requests) == 1
    wait_until(fixture.app, lambda: not listener.paused, timeout=3)
