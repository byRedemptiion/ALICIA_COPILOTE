from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from alicia.capture import primary
from alicia.core.ports import CaptureError, UnsupportedPlatformError


@pytest.mark.parametrize("operation", ["list", "capture"])
def test_primary_screen_is_import_safe_and_explicit_off_windows(monkeypatch, operation):
    monkeypatch.setattr(primary.sys, "platform", "linux")
    source = primary.PrimaryScreenCapture()
    with pytest.raises(UnsupportedPlatformError, match="Windows"):
        if operation == "list":
            source.list_windows()
        else:
            source.capture(primary.PRIMARY_SCREEN)


def fake_source(monkeypatch, width=100, height=60):
    monkeypatch.setattr(primary.sys, "platform", "win32")
    source = primary.PrimaryScreenCapture()
    source._api = SimpleNamespace(dimensions=lambda: (width, height))
    return source


def test_primary_descriptor_is_available_without_opening_a_capture(monkeypatch):
    source = fake_source(monkeypatch)
    grab = Mock()
    monkeypatch.setattr(primary.ImageGrab, "grab", grab)
    assert source.list_windows() == [primary.PRIMARY_SCREEN]
    grab.assert_not_called()


def test_capture_uses_primary_physical_bounds_and_returns_png(monkeypatch):
    source = fake_source(monkeypatch)
    grab = Mock(return_value=Image.new("RGBA", (100, 60), "#33aa88"))
    monkeypatch.setattr(primary.ImageGrab, "grab", grab)
    frame = source.capture(primary.PRIMARY_SCREEN)
    grab.assert_called_once_with(
        bbox=(0, 0, 100, 60), all_screens=True, include_layered_windows=True
    )
    with Image.open(BytesIO(frame.png)) as image:
        assert image.size == (100, 60)
        assert image.mode == "RGB"
        assert image.getpixel((0, 0)) == (51, 170, 136)
    assert frame.window == primary.PRIMARY_SCREEN
    assert frame.width == 100 and frame.height == 60
    assert frame.capture_id and frame.captured_at.utcoffset().total_seconds() == 0


def test_capture_never_changes_a_window_request_to_a_desktop_capture(monkeypatch):
    source = fake_source(monkeypatch)
    grab = Mock()
    monkeypatch.setattr(primary.ImageGrab, "grab", grab)
    with pytest.raises(CaptureError, match="source"):
        source.capture(replace(primary.PRIMARY_SCREEN, handle=42))
    grab.assert_not_called()


@pytest.mark.parametrize("width,height", [(0, 60), (100, -1), (100_000, 100_000)])
def test_capture_rejects_invalid_screen_dimensions(monkeypatch, width, height):
    source = fake_source(monkeypatch, width, height)
    grab = Mock()
    monkeypatch.setattr(primary.ImageGrab, "grab", grab)
    with pytest.raises(CaptureError, match="dimensions"):
        source.capture(primary.PRIMARY_SCREEN)
    grab.assert_not_called()


def test_mismatched_image_dimensions_are_not_reported_as_success(monkeypatch):
    source = fake_source(monkeypatch)
    monkeypatch.setattr(primary.ImageGrab, "grab", lambda **kwargs: Image.new("RGB", (50, 30)))
    with pytest.raises(CaptureError, match="dimensions"):
        source.capture(primary.PRIMARY_SCREEN)


def test_native_errors_are_sanitized(monkeypatch):
    source = fake_source(monkeypatch)
    monkeypatch.setattr(primary.ImageGrab, "grab", Mock(side_effect=OSError("private details")))
    with pytest.raises(CaptureError) as error:
        source.capture(primary.PRIMARY_SCREEN)
    assert "private details" not in str(error.value)


def test_dpi_awareness_is_configured_before_dimensions_are_read(monkeypatch):
    api = SimpleNamespace(
        GetSystemMetrics=Mock(side_effect=[2560, 1440]),
        SetProcessDpiAwarenessContext=Mock(return_value=True),
        SetProcessDPIAware=Mock(),
    )
    monkeypatch.setattr(primary.ctypes, "WinDLL", Mock(return_value=api), raising=False)
    native = primary._PrimaryAPI()
    api.SetProcessDpiAwarenessContext.assert_called_once()
    api.GetSystemMetrics.assert_not_called()
    assert native.dimensions() == (2560, 1440)
    assert api.GetSystemMetrics.call_args_list[0].args == (0,)
    assert api.GetSystemMetrics.call_args_list[1].args == (1,)
    api.SetProcessDPIAware.assert_not_called()
