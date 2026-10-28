from threading import Event

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from alicia.capture.demo import DemoCapture
from alicia.config import Settings
from alicia.core.models import AnalysisResult
from alicia.core.ports import AnalysisError, CaptureError
from alicia.ui.main_window import MainWindow
from alicia.ui.smoke import run_smoke, wait_until


class TestVision:
    __test__ = False

    def __init__(self):
        self.requests = []
        self.error = None
        self.started = Event()
        self.release = Event()
        self.release.set()

    def analyze(self, request):
        self.requests.append(request)
        self.started.set()
        if not self.release.wait(timeout=3):
            raise AnalysisError("Test worker timeout")
        if self.error:
            raise self.error
        return AnalysisResult(
            "Réponse de test explicite", "fake-test", 0.1, request.frame.capture_id
        )


@pytest.fixture
def window(app, tmp_path):
    vision = TestVision()
    widget = MainWindow(Settings(log_directory=tmp_path), DemoCapture(), vision, demo=True)
    widget.show()
    wait_until(app, lambda: not widget.jobs)
    yield widget
    vision.release.set()
    wait_until(app, lambda: not widget.jobs)
    widget.close()
    wait_until(app, lambda: not widget.jobs and not widget.isVisible())
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def capture(app, window):
    window.start_button.click()
    window.capture_button.click()
    wait_until(app, lambda: not window.jobs)
    assert window.session.frame is not None
    window.question.setPlainText("Question de test")
    window.consent.setChecked(True)


def test_local_smoke_and_screenshot(app, window, tmp_path):
    screenshot = tmp_path / "preview.png"
    assert run_smoke(app, window, screenshot) == 0
    assert screenshot.stat().st_size > 1000
    assert window.vision_provider.requests == []


def test_analysis_uses_exact_preview_and_does_not_auto_speak(app, window):
    capture(app, window)
    frame = window.session.frame
    window.analyze_button.click()
    window.analyze_button.click()
    wait_until(app, lambda: not window.jobs)
    assert len(window.vision_provider.requests) == 1
    assert window.vision_provider.requests[0].frame is frame
    assert window.answer.toPlainText() == "Réponse de test explicite"
    assert window.avatar.state != "speaking"
    assert window.speak_button.isEnabled()


def test_stop_discards_analysis_inflight(app, window):
    capture(app, window)
    provider = window.vision_provider
    provider.release.clear()
    window.analyze_button.click()
    wait_until(app, provider.started.is_set)
    window.stop_button.click()
    provider.release.set()
    wait_until(app, lambda: not window.jobs)
    assert window.session.result is None
    assert window.answer.toPlainText() == ""
    assert window.state_label.text() == "Observation arrêtée"


def test_failed_reanalysis_clears_old_answer(app, window):
    capture(app, window)
    window.analyze_button.click()
    wait_until(app, lambda: not window.jobs)
    assert window.speak_button.isEnabled()
    window.vision_provider.error = AnalysisError("Échec réseau de test")
    window.analyze_button.click()
    wait_until(app, lambda: not window.jobs)
    assert window.session.result is None
    assert not window.speak_button.isEnabled()
    assert window.answer.toPlainText() == ""


def test_failed_recapture_clears_old_frame(app, window, monkeypatch):
    capture(app, window)

    def fail(_window):
        raise CaptureError("Fenêtre fermée")

    monkeypatch.setattr(window.capture_source, "capture", fail)
    window.capture_button.click()
    wait_until(app, lambda: not window.jobs)
    assert window.session.frame is None
    assert not window.analyze_button.isEnabled()
    assert not window.consent.isChecked()


def test_stopping_voice_during_analysis_does_not_discard_analysis(app, window):
    capture(app, window)
    provider = window.vision_provider
    provider.release.clear()
    window.analyze_button.click()
    wait_until(app, provider.started.is_set)
    window.stop_audio()
    provider.release.set()
    wait_until(app, lambda: not window.jobs)
    assert window.session.result is not None


def test_cancelled_speech_does_not_play_late_result(app, window, monkeypatch):
    capture(app, window)
    window.analyze_button.click()
    wait_until(app, lambda: not window.jobs)
    started, release = Event(), Event()
    played = []

    def speech(_text):
        started.set()
        release.wait(timeout=3)
        return b"fake audio for test only"

    monkeypatch.setattr(window.speech_provider, "synthesize", speech)
    monkeypatch.setattr(window.playback, "play", played.append)
    window.speak_button.click()
    wait_until(app, started.is_set)
    window.stop_audio()
    release.set()
    wait_until(app, lambda: not window.jobs)
    assert played == []


def test_close_waits_for_worker_then_closes_automatically(app, window):
    capture(app, window)
    provider = window.vision_provider
    provider.release.clear()
    window.analyze_button.click()
    wait_until(app, provider.started.is_set)
    window.close()
    assert window.close_pending
    assert not window.centralWidget().isEnabled()
    provider.release.set()
    wait_until(app, lambda: not window.isVisible())
    assert window.session.result is None


def test_avatar_picture_and_speaking_state_are_local(app, window, tmp_path):
    from PySide6.QtGui import QColor, QImage

    picture = QImage(100, 100, QImage.Format_RGB32)
    picture.fill(QColor("#b8a8e9"))
    path = tmp_path / "portrait.png"
    assert picture.save(str(path))
    assert window.avatar.load_picture(str(path))
    window._speaking(True)
    assert window.avatar.state == "speaking"
    assert window.avatar.timer.isActive()
    window._speaking(False)
    assert not window.avatar.timer.isActive()
    assert window.vision_provider.requests == []


def test_preview_fits_entire_frame_after_resize(app, window):
    capture(app, window)
    window.resize(1000, 780)
    app.processEvents()
    pixmap = window.preview.pixmap()
    bounds = window.preview.contentsRect()
    assert pixmap.width() <= bounds.width()
    assert pixmap.height() <= bounds.height()
    assert abs(pixmap.width() / pixmap.height() - 960 / 540) < 0.02
    assert window.preview.geometry().bottom() < window.capture_details.geometry().top()
