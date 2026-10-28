from dataclasses import replace

from alicia.capture.demo import DemoCapture
from alicia.core.models import AnalysisResult
from alicia.core.session import Session


def test_stop_discards_inflight_capture_and_analysis():
    source = DemoCapture()
    session = Session()
    session.start(source.window)
    generation = session.generation
    frame = source.capture(source.window)
    assert session.accept_frame(generation, frame)
    session.stop()
    assert not session.accept_frame(generation, frame)
    assert not session.accept_result(
        generation, AnalysisResult("Ancien", "fake", 0, frame.capture_id)
    )
    assert session.frame is None


def test_new_capture_invalidates_previous_answer():
    source = DemoCapture()
    session = Session()
    session.start(source.window)
    first, second = source.capture(source.window), source.capture(source.window)
    assert session.accept_frame(session.generation, first)
    result = AnalysisResult("Test", "fake", 0, first.capture_id)
    assert session.accept_result(session.generation, result)
    assert session.accept_frame(session.generation, second)
    assert session.result is None
    assert not session.accept_result(session.generation, result)


def test_capture_from_another_window_is_rejected():
    source = DemoCapture()
    session = Session()
    session.start(source.window)
    frame = source.capture(source.window)
    assert not session.accept_frame(
        session.generation, replace(frame, window=replace(source.window, handle=23))
    )
