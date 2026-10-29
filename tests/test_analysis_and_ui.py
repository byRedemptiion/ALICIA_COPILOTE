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
