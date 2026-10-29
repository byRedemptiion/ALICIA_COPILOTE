import numpy as np
import pytest

from alice.core.capture.backends import DEMO_WINDOW, DemoBackend
from alice.core.capture.models import Rect, WindowInfo, image_from_bgra, is_black
from alice.core.capture.service import CaptureService
from alice.core.errors import CaptureError


def bgra(color, size=(40, 60)):
    b, g, r = color
    pixels = np.zeros(size + (4,), dtype=np.uint8)
    pixels[:, :] = (b, g, r, 255)
    return pixels


class StubBackend:
    def __init__(self, name, result):
        self.name = name
        self.result = result
        self.calls = 0

    def grab(self, window):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def service(*backends):
    return CaptureService(lambda: [DEMO_WINDOW], lambda w: w, lambda w: list(backends))


def test_black_detection():
    assert is_black(bgra((0, 0, 0)))
    assert is_black(bgra((3, 3, 3)))
    assert not is_black(bgra((0, 0, 200)))


def test_bgra_is_converted_to_rgb():
    image = image_from_bgra(bgra((10, 20, 200)))
    assert image.mode == "RGB"
    assert image.getpixel((0, 0)) == (200, 20, 10)


def test_first_working_backend_is_used():
    first = StubBackend("wgc-window", bgra((0, 0, 255)))
    second = StubBackend("printwindow", bgra((255, 0, 0)))
    frame = service(first, second).capture(DEMO_WINDOW)
    assert frame.backend == "wgc-window"
    assert frame.notes == ()
    assert second.calls == 0


def test_black_image_falls_back_and_says_so():
    black = StubBackend("wgc-window", bgra((0, 0, 0)))
    monitor = StubBackend("wgc-monitor", bgra((0, 255, 0)))
    frame = service(black, monitor).capture(DEMO_WINDOW)
    assert frame.backend == "wgc-monitor"
    assert "image noire" in frame.notes[0]


def test_error_falls_back_then_reports_every_attempt():
    failing = StubBackend("wgc-window", CaptureError("refus", detail="E_ACCESSDENIED"))
    black = StubBackend("printwindow", bgra((0, 0, 0)))
    with pytest.raises(CaptureError) as info:
        service(failing, black).capture(DEMO_WINDOW)
    assert "E_ACCESSDENIED" in info.value.detail
    assert "printwindow: image noire" in info.value.detail


def test_recent_frames_are_bounded():
    svc = CaptureService(lambda: [], lambda w: w, lambda w: [DemoBackend()], keep_last=2)
    for _ in range(3):
        svc.capture(DEMO_WINDOW)
    assert len(svc.recent) == 2
    assert svc.last is svc.recent[-1]


def test_fullscreen_detection():
    monitor = Rect(0, 0, 1920, 1080)
    full = WindowInfo(1, "Overwatch", 2, rect=Rect(0, 0, 1920, 1080), monitor_rect=monitor)
    windowed = WindowInfo(1, "Overwatch", 2, rect=Rect(100, 100, 1380, 820), monitor_rect=monitor)
    assert full.fullscreen
    assert not windowed.fullscreen


def test_windows_capture_refuses_other_platforms(monkeypatch):
    import sys

    from alice.core.capture.win32 import Win32
    from alice.core.errors import UnsupportedPlatformError

    if sys.platform == "win32":
        pytest.skip("test des plateformes non Windows")
    with pytest.raises(UnsupportedPlatformError):
        Win32()
