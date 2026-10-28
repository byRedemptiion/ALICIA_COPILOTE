from threading import Event
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from alicia.actions.models import ActionPlan
from alicia.audio.ports import SpeechError
from alicia.capture.demo import DemoCapture
from alicia.config import Settings
from alicia.ui.main_window import MainWindow
from alicia.ui.smoke import wait_until


class BlockingCapture(DemoCapture):
    def __init__(self):
        self.count = 0
        self.started, self.release = Event(), Event()
        self.release.set()

    def capture(self, source):
        self.count += 1
        self.started.set()
        assert self.release.wait(3)
        return super().capture(source)


class Planner:
    def __init__(self):
        self.requests = []

    def plan(self, text, history=()):
        self.requests.append(text)
        return ActionPlan("clarify", message="Consigne de test reçue.")


class DiagnosticListener:
    def __init__(self, _path, on_text, on_error, on_activity, **_kwargs):
        self.on_error, self.on_activity = on_error, on_activity
        self.on_status = self.on_level = None
        self.active = self.paused = False

    def start(self, _device):
        self.active = True

    def stop(self):
        self.active, self.paused = False, True

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False


@pytest.fixture
def preview_window(app):
    capture, planner = BlockingCapture(), Planner()
    window = MainWindow(Settings(capture_interval_ms=10000), capture, None, demo=True)
    window.actions.planner = planner
    window.show()
    wait_until(app, lambda: not window.jobs)
    window.conversation.continuous.setChecked(False)
    window.start()
    window.consent.setChecked(True)
    fixture = SimpleNamespace(window=window, capture=capture, planner=planner, app=app)
    yield fixture
    capture.release.set()
    window.stop()
    wait_until(app, lambda: not window.jobs)
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def block_preview(fixture):
    fixture.capture.started.clear()
    fixture.capture.release.clear()
    fixture.window.capture(background=True)
    wait_until(fixture.app, fixture.capture.started.is_set)


def test_preview_does_not_toggle_capture_or_request_controls(preview_window):
    fixture = preview_window
    fixture.window.question.setPlainText("Une demande")
    names = ("capture_button", "send_button", "refresh_button", "windows")
    before = [getattr(fixture.window, name).isEnabled() for name in names]
    assert all(before)
    block_preview(fixture)
    assert fixture.window.preview_busy and not fixture.window.foreground_busy
    assert [getattr(fixture.window, name).isEnabled() for name in names] == before
    fixture.capture.release.set()
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    assert [getattr(fixture.window, name).isEnabled() for name in names] == before


def test_repeated_capture_clicks_during_preview_run_once_after_it(preview_window):
    fixture = preview_window
    block_preview(fixture)
    for _ in range(3):
        fixture.window.capture_button.click()
    assert fixture.capture.count == 1
    fixture.capture.release.set()
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    assert fixture.capture.count == 2
    assert fixture.window.session.frame is not None


def test_request_clicked_during_preview_is_frozen_and_not_lost(preview_window):
    fixture = preview_window
    block_preview(fixture)
    fixture.window.question.setPlainText("Consigne au moment du clic")
    fixture.window.send_button.click()
    fixture.window.question.setPlainText("Texte changé ensuite")
    fixture.capture.release.set()
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    assert fixture.planner.requests == ["Consigne au moment du clic"]
    assert fixture.capture.count == 1
    assert fixture.window.answer.toPlainText() == "Consigne de test reçue."


def test_only_latest_request_is_queued_during_a_preview(preview_window):
    fixture = preview_window
    block_preview(fixture)
    fixture.window.capture_button.click()
    fixture.window.question.setPlainText("Première consigne")
    fixture.window.send_button.click()
    fixture.window.question.setPlainText("Dernière consigne")
    fixture.window.send_button.click()
    fixture.capture.release.set()
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    assert fixture.planner.requests == ["Dernière consigne"]
    assert fixture.capture.count == 1


@pytest.mark.parametrize("cancel", ["stop", "permission", "source"])
def test_cancel_discards_queued_request_before_preview_returns(preview_window, cancel):
    fixture = preview_window
    block_preview(fixture)
    fixture.window.question.setPlainText("Consigne annulée")
    fixture.window.send_button.click()
    if cancel == "stop":
        fixture.window.stop_button.click()
    elif cancel == "permission":
        fixture.window.consent.setChecked(False)
    else:
        fixture.window.windows.setCurrentIndex(-1)
    fixture.capture.release.set()
    wait_until(fixture.app, lambda: not fixture.window.jobs)
    assert fixture.planner.requests == []
    assert fixture.window.answer.toPlainText() == ""


def test_microphone_status_distinguishes_loading_from_actual_readiness(preview_window):
    window = preview_window.window
    window.conversation.listener_factory = DiagnosticListener
    window.conversation.toggle_listening()
    listener = window.conversation.listener
    assert "Initialisation" in window.conversation.status.text()
    assert "Microphone prêt" not in window.events.toPlainText()
    listener.on_status("loading_model")
    assert "Chargement du modèle" in window.conversation.status.text()
    listener.on_level(0.08)
    assert window.conversation.level.value() > 0
    listener.on_status("opening_microphone")
    assert "Ouverture du microphone" in window.conversation.status.text()
    listener.on_activity(True)
    listener.on_activity(True)
    assert "En attente" in window.conversation.status.text()
    assert window.events.toPlainText().count("Microphone prêt") == 1


def test_microphone_error_remains_visible_after_listener_is_stopped(preview_window):
    window = preview_window.window
    window.conversation.listener_factory = DiagnosticListener
    window.conversation.toggle_listening()
    listener = window.conversation.listener
    listener.on_error("Le microphone est indisponible.")
    assert window.conversation.listener is None
    assert "microphone est indisponible" in window.conversation.status.text()
    assert window.conversation.level.value() == 0
    listener.on_status("ready")
    listener.on_activity(True)
    assert "Microphone prêt" not in window.events.toPlainText()


def test_synchronous_microphone_setup_error_is_visible(preview_window):
    def unavailable(*_args, **_kwargs):
        raise SpeechError("Modèle de reconnaissance absent.")

    window = preview_window.window
    window.conversation.listener_factory = unavailable
    window.conversation.toggle_listening()
    assert "Modèle de reconnaissance absent" in window.conversation.status.text()
