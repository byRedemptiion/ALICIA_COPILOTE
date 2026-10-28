from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from alicia.capture import win32
from alicia.core.models import WindowInfo
from alicia.core.ports import CaptureError, UnsupportedPlatformError


def test_non_windows_capture_has_explicit_error(monkeypatch):
    monkeypatch.setattr(win32.sys, "platform", "linux")
    capture = win32.WindowsCapture()
    with pytest.raises(UnsupportedPlatformError, match="Windows"):
        capture.list_windows()
    with pytest.raises(UnsupportedPlatformError, match="Windows"):
        capture.capture(WindowInfo(handle=1, title="Game", process_id=123))


def test_bgra_pixels_are_encoded_without_alpha_and_in_order():
    data = win32._png_from_bgra(bytes([0, 0, 255, 0, 0, 255, 0, 255]), 2, 1)
    image = Image.open(BytesIO(data))
    assert image.size == (2, 1)
    assert image.getpixel((0, 0)) == (255, 0, 0)
    assert image.getpixel((1, 0)) == (0, 255, 0)


def test_black_image_is_not_presented_as_verified_capture():
    with pytest.raises(CaptureError, match="noire"):
        win32._png_from_bgra(b"\x00" * 16, 2, 2)


def make_api():
    return SimpleNamespace(
        user32=SimpleNamespace(
            GetDC=Mock(return_value=11), ReleaseDC=Mock(), PrintWindow=Mock(return_value=1)
        ),
        gdi32=SimpleNamespace(
            CreateCompatibleDC=Mock(return_value=12),
            CreateCompatibleBitmap=Mock(return_value=13),
            SelectObject=Mock(return_value=14),
            DeleteObject=Mock(),
            DeleteDC=Mock(),
            GetDIBits=Mock(return_value=2),
        ),
    )


def test_capture_failure_restores_selected_bitmap_and_releases_resources():
    api = make_api()
    api.user32.PrintWindow.return_value = 0
    with pytest.raises(CaptureError, match="PrintWindow"):
        win32._capture_pixels(api, 100, 2, 2)
    assert api.gdi32.SelectObject.call_args_list[-1].args == (12, 14)
    api.gdi32.DeleteObject.assert_called_once_with(13)
    api.gdi32.DeleteDC.assert_called_once_with(12)
    api.user32.ReleaseDC.assert_called_once_with(100, 11)


def test_pixel_failure_releases_bitmap_after_deselecting():
    api = make_api()
    api.gdi32.GetDIBits.return_value = 0
    with pytest.raises(CaptureError, match="pixels"):
        win32._capture_pixels(api, 100, 2, 2)
    assert api.gdi32.SelectObject.call_count == 2
    api.gdi32.DeleteObject.assert_called_once_with(13)
    api.gdi32.DeleteDC.assert_called_once_with(12)
    api.user32.ReleaseDC.assert_called_once_with(100, 11)


def test_bitmap_allocation_failure_releases_only_acquired_resources():
    api = make_api()
    api.gdi32.CreateCompatibleBitmap.return_value = 0
    with pytest.raises(CaptureError, match="allouer"):
        win32._capture_pixels(api, 100, 2, 2)
    api.gdi32.DeleteObject.assert_not_called()
    api.gdi32.DeleteDC.assert_called_once_with(12)
    api.user32.ReleaseDC.assert_called_once_with(100, 11)


@pytest.mark.parametrize(
    ("valid", "process_id", "title", "minimized", "expected"),
    [
        (False, 123, "Game", False, "fermée"),
        (True, 456, "Game", False, "changé"),
        (True, 123, "Another window", False, "changé"),
        (True, 123, "Game", True, "minimisée"),
    ],
)
def test_invalid_window_is_rejected_before_native_capture(
    monkeypatch, valid, process_id, title, minimized, expected
):
    api = SimpleNamespace(
        user32=SimpleNamespace(
            IsWindow=Mock(return_value=valid), IsIconic=Mock(return_value=minimized)
        ),
        process_id=Mock(return_value=process_id),
        title=Mock(return_value=title),
    )
    capture = win32.WindowsCapture()
    monkeypatch.setattr(capture, "_require_api", lambda: api)
    native_capture = Mock()
    monkeypatch.setattr(win32, "_capture_pixels", native_capture)
    with pytest.raises(CaptureError, match=expected):
        capture.capture(WindowInfo(handle=1, title="Game", process_id=123))
    native_capture.assert_not_called()
