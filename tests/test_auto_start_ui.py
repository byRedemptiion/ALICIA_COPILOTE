from datetime import UTC, datetime
from io import BytesIO
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image
from PySide6.QtCore import QCoreApplication, QEvent

from alicia.capture.primary import PRIMARY_SCREEN
from alicia.config import Settings
from alicia.core.models import AnalysisResult, CapturedFrame, WindowInfo
from alicia.core.ports import AnalysisError
from alicia.research.search import SearchError
from alicia.ui.main_window import MainWindow
from alicia.ui.smoke import wait_until


class FakeListener:
    def __init__(self, model_path, on_text, on_error, on_activity, on_partial=None):
        self.on_text, self.on_error, self.on_activity = on_text, on_error, on_activity
        self.active = self.paused = False

    def start(self, _device=None):
        self.active, self.paused = True, False
        self.on_activity(True)

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def stop(self):
        self.active, self.paused = False, True
        self.on_activity(False)


class FakeDesktop:
    alternative = WindowInfo(42, "Fenêtre facultative", 100)

    def __init__(self):
        output = BytesIO()
        Image.new("RGB", (320, 180), "#223344").save(output, format="PNG")
        self.png = output.getvalue()
        self.captures = []
        self.list_started = Event()
        self.list_release = Event()
        self.list_release.set()

    def list_windows(self):
        self.list_started.set()
        if not self.list_release.wait(timeout=3):
            raise RuntimeError("Fake enumeration timed out")
        return [PRIMARY_SCREEN, self.alternative]

    def capture(self, window):
        self.captures.append(window)
        return CapturedFrame(self.png, 320, 180, window, datetime.now(UTC), uuid4().hex)


class FakeVision:
    def __init__(self):
        self.requests = []
        self.started = Event()
        self.release = Event()
        self.release.set()
        self.error = None

    def analyze(self, request):
        self.requests.append(request)
        self.started.set()
        if not self.release.wait(timeout=3):
            raise AnalysisError("Fake analysis timed out")
        if self.error:
            raise self.error
        return AnalysisResult("Réponse de test", "fake", 0.01, request.frame.capture_id)


@pytest.fixture
def auto_factory(app, tmp_path, monkeypatch):
    fixtures = []

    def create(*, demo=False, blocked_list=False):
        source, vision = FakeDesktop(), FakeVision()
        if blocked_list:
            source.list_release.clear()
        settings = Settings(log_directory=tmp_path, capture_interval_ms=10000)
        window = MainWindow(settings, source, vision, demo=demo, autostart=True)
        listeners = []

        def listener_factory(*args, **kwargs):
            listener = FakeListener(*args, **kwargs)
            listeners.append(listener)
            return listener

        # No event processing has occurred: the source worker's queued result
        # cannot start a real microphone before this local factory is installed.
        window.conversation.listener_factory = listener_factory
        monkeypatch.setattr(window.speech_provider, "synthesize", lambda _text: b"fake audio")
        monkeypatch.setattr(window.playback, "play", lambda _audio: None)
        window.show()
        fixture = SimpleNamespace(
            window=window, source=source, vision=vision, listeners=listeners, app=app
        )
        fixtures.append(fixture)
        return fixture

    yield create
    for fixture in fixtures:
        fixture.source.list_release.set()
        fixture.vision.release.set()
        fixture.window.stop()
        wait_until(app, lambda: not fixture.window.jobs)
        fixture.window.close()
        fixture.window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def ready(fixture):
    wait_until(
        fixture.app,
        lambda: (
            fixture.window.session.active
            and bool(fixture.listeners)
            and fixture.listeners[-1].active
            and not fixture.window.jobs
        ),
    )
    return fixture.listeners[-1]


def test_launch_observes_primary_and_opens_microphone_without_click(auto_factory):
    fixture = auto_factory()
    listener = ready(fixture)
    window = fixture.window
    assert window.windows.currentData() == PRIMARY_SCREEN
    assert window.session.window == PRIMARY_SCREEN
    assert window.consent.isChecked()
    assert listener.active and not listener.paused
    assert window.conversation.timer.isActive()
    assert fixture.vision.requests == []


def test_primary_source_and_microphone_need_no_dropdown_or_activation_button(auto_factory):
    fixture = auto_factory()
    ready(fixture)
    assert not fixture.window.windows.isVisible()
    assert not fixture.window.refresh_button.isVisible()
    assert not fixture.window.conversation.toggle.isVisible()
    fixture.window.source_button.click()
    assert fixture.window.windows.isVisible()


def test_stop_disables_capture_listening_and_queued_wake_callbacks(auto_factory):
    fixture = auto_factory()
    listener = ready(fixture)
    delayed_callback = listener.on_text
    fixture.window.stop_button.click()
    delayed_callback("Alicia, décris cet écran")
    fixture.app.processEvents()
    assert not listener.active
    assert not fixture.window.session.active
    assert not fixture.window.conversation.timer.isActive()
    assert fixture.source.captures == []
    assert fixture.vision.requests == []


def test_stop_before_enumeration_returns_prevents_delayed_automatic_restart(auto_factory):
    fixture = auto_factory(blocked_list=True)
    assert fixture.source.list_started.wait(timeout=1)
    fixture.window.stop()
    fixture.source.list_release.set()
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    fixture.app.processEvents()
    assert fixture.listeners == []
    assert not fixture.window.session.active
    assert not fixture.window.startup_timer.isActive()


def test_resume_reopens_microphone_and_primary_observation(auto_factory):
    fixture = auto_factory()
    first = ready(fixture)
    fixture.window.stop_button.click()
    fixture.window.start_button.click()
    wait_until(fixture.app, lambda: len(fixture.listeners) == 2)
    assert not first.active
    assert fixture.listeners[-1].active
    assert fixture.window.session.window == PRIMARY_SCREEN
    assert fixture.window.consent.isChecked()


def test_changing_source_stops_listening_and_clears_old_context(auto_factory):
    fixture = auto_factory()
    listener = ready(fixture)
    fixture.window.session.memory.append("Question précédente", "Réponse précédente")
    fixture.window.source_button.click()
    fixture.window.windows.setCurrentIndex(1)
    assert not listener.active
    assert not fixture.window.session.active
    assert fixture.window.session.memory.snapshot() == ()
    assert fixture.window.source_label.text() == fixture.source.alternative.title


def test_demo_never_starts_listening_even_with_autostart_requested(auto_factory):
    fixture = auto_factory(demo=True)
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    fixture.app.processEvents()
    assert fixture.listeners == []
    assert not fixture.window.automatic_mode
    assert not fixture.window.session.active


def test_manual_capture_preserves_automatic_microphone_and_consent(auto_factory):
    fixture = auto_factory()
    listener = ready(fixture)
    fixture.window.capture_button.click()
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    wait_until(fixture.app, lambda: not listener.paused)
    assert fixture.window.session.frame is not None
    assert fixture.window.consent.isChecked()
    assert fixture.window.conversation.listener is listener
    assert listener.active


@pytest.mark.parametrize("failure", ["analysis", "web"])
def test_processing_errors_keep_automatic_microphone_available(auto_factory, failure):
    fixture = auto_factory()
    listener = ready(fixture)
    fixture.window.conversation.auto_voice.setChecked(False)
    if failure == "analysis":
        fixture.vision.error = AnalysisError("Échec IA de test")
    else:

        class FailedSearch:
            def search(self, _question):
                raise SearchError("Échec web de test")

        fixture.window.research_provider = FailedSearch()
        fixture.window.conversation.web.setChecked(True)
    listener.on_text("Alicia, décris cet écran")
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    wait_until(fixture.app, lambda: not listener.paused)
    assert listener.active
    assert fixture.window.conversation.listener is listener
    assert fixture.window.consent.isChecked()
    assert fixture.window.conversation.phase == "idle"
    assert fixture.window.session.result is None


def test_context_records_the_question_sent_even_if_editor_changes_during_analysis(auto_factory):
    fixture = auto_factory()
    ready(fixture)
    fixture.window.capture(background=True)
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    fixture.vision.release.clear()
    fixture.window.question.setPlainText("Question réellement envoyée")
    fixture.window.analyze_button.click()
    wait_until(fixture.app, fixture.vision.started.is_set)
    fixture.window.question.setPlainText("Texte changé pendant le calcul")
    fixture.vision.release.set()
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    history = fixture.window.session.memory.snapshot()
    assert len(history) == 1
    assert history[0].user == "Question réellement envoyée"
    fixture.window.question.setPlainText("Et celui-là ?")
    fixture.window.analyze_button.click()
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    assert fixture.vision.requests[-1].history == history


def test_late_answer_after_stop_cannot_repopulate_cleared_context(auto_factory):
    fixture = auto_factory()
    ready(fixture)
    fixture.window.capture(background=True)
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    fixture.vision.release.clear()
    fixture.window.question.setPlainText("Question annulée")
    fixture.window.analyze_button.click()
    wait_until(fixture.app, fixture.vision.started.is_set)
    fixture.window.stop_button.click()
    fixture.vision.release.set()
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    assert fixture.window.session.memory.snapshot() == ()
    assert fixture.window.session.result is None
