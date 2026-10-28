import multiprocessing
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from alicia.capture import isolated
from alicia.capture.primary import PRIMARY_SCREEN
from alicia.core.models import WindowInfo
from alicia.core.ports import CaptureError, UnsupportedPlatformError


def test_non_windows_isolation_fails_without_spawning(monkeypatch):
    monkeypatch.setattr(isolated.sys, "platform", "linux")
    context = Mock()
    monkeypatch.setattr(isolated.multiprocessing, "get_context", context)
    with pytest.raises(UnsupportedPlatformError, match="Windows"):
        isolated.IsolatedWindowsCapture().list_windows()
    context.assert_not_called()


def fake_context(monkeypatch, *, ready=True, packet=("ok", []), receive_error=None):
    monkeypatch.setattr(isolated.sys, "platform", "win32")
    receiver = Mock()
    receiver.poll.return_value = ready
    receiver.recv.return_value = packet
    receiver.recv.side_effect = receive_error
    sender = Mock()
    process = Mock()
    process.is_alive.return_value = False
    context = SimpleNamespace(
        Pipe=Mock(return_value=(receiver, sender)), Process=Mock(return_value=process)
    )
    monkeypatch.setattr(isolated.multiprocessing, "get_context", Mock(return_value=context))
    return receiver, sender, process


def test_timeout_terminates_stuck_process_and_closes_pipes(monkeypatch):
    receiver, sender, process = fake_context(monkeypatch, ready=False)
    process.is_alive.side_effect = [True, False, False]
    with pytest.raises(CaptureError, match="délai"):
        isolated.IsolatedWindowsCapture(list_timeout=0.1).list_windows()
    receiver.poll.assert_called_once_with(0.1)
    process.terminate.assert_called_once()
    process.close.assert_called_once()
    receiver.close.assert_called_once()
    assert sender.close.call_count >= 1


def test_eof_is_reported_without_leaking_worker_details(monkeypatch):
    receiver, sender, process = fake_context(monkeypatch, receive_error=EOFError("private data"))
    with pytest.raises(CaptureError, match="indisponible") as error:
        isolated.IsolatedWindowsCapture().list_windows()
    assert "private data" not in str(error.value)
    receiver.close.assert_called_once()
    process.close.assert_called_once()


def test_list_filters_actual_application_pid(monkeypatch):
    windows = [
        WindowInfo(handle=1, title="Alicia", process_id=100),
        WindowInfo(handle=2, title="Game", process_id=200),
    ]
    fake_context(monkeypatch, packet=("ok", windows))
    monkeypatch.setattr(isolated.os, "getpid", lambda: 100)
    assert isolated.IsolatedWindowsCapture().list_windows() == windows[1:]


def test_native_public_error_is_preserved(monkeypatch):
    fake_context(monkeypatch, packet=("capture_error", "Restaurez la fenêtre minimisée."))
    with pytest.raises(CaptureError, match="minimisée"):
        isolated.IsolatedWindowsCapture().list_windows()


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_invalid_timeouts_are_rejected(value):
    with pytest.raises(ValueError):
        isolated.IsolatedWindowsCapture(capture_timeout=value)


def test_cleanup_escalates_to_kill_if_termination_does_not_stop_process():
    process = Mock()
    process.is_alive.side_effect = [True, True, False]
    isolated._stop_process(process, started=True)
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    process.close.assert_called_once()


@pytest.mark.skipif(sys.platform == "win32", reason="Exercises the non-Windows child outcome")
def test_spawned_worker_reports_unsupported_platform_without_qt():
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=isolated._capture_worker, args=(sender, "list", None))
    process.start()
    sender.close()
    try:
        assert receiver.poll(5), "Spawned worker did not return a platform result"
        status, message = receiver.recv()
        assert status == "unsupported"
        assert "Windows" in message
        process.join(timeout=2)
        assert process.exitcode == 0
    finally:
        receiver.close()
        isolated._stop_process(process, started=True)


def test_desktop_source_lists_primary_before_optional_windows(monkeypatch):
    monkeypatch.setattr(isolated.sys, "platform", "win32")
    window = WindowInfo(handle=42, title="Game", process_id=100)
    monkeypatch.setattr(isolated.IsolatedWindowsCapture, "list_windows", lambda _self: [window])
    assert isolated.DesktopCaptureSource().list_windows() == [PRIMARY_SCREEN, window]


def test_desktop_source_keeps_primary_if_window_enumeration_fails(monkeypatch):
    monkeypatch.setattr(isolated.sys, "platform", "win32")

    def fail(_self):
        raise CaptureError("Window enumeration unavailable")

    monkeypatch.setattr(isolated.IsolatedWindowsCapture, "list_windows", fail)
    assert isolated.DesktopCaptureSource().list_windows() == [PRIMARY_SCREEN]


def test_desktop_source_remains_unsupported_off_windows(monkeypatch):
    monkeypatch.setattr(isolated.sys, "platform", "linux")
    with pytest.raises(UnsupportedPlatformError):
        isolated.DesktopCaptureSource().list_windows()


def test_desktop_capture_uses_bounded_primary_child_operation(monkeypatch):
    from alicia.capture.demo import DemoCapture

    frame = DemoCapture().capture(DemoCapture.window)
    run = Mock(return_value=frame)
    monkeypatch.setattr(isolated.DesktopCaptureSource, "_run", run)
    assert isolated.DesktopCaptureSource(capture_timeout=3).capture(PRIMARY_SCREEN) is frame
    run.assert_called_once_with("primary", PRIMARY_SCREEN, 3)


def test_desktop_capture_preserves_explicit_window_requests(monkeypatch):
    window = WindowInfo(handle=42, title="Game", process_id=100)
    capture = Mock(return_value="window-result")
    monkeypatch.setattr(isolated.IsolatedWindowsCapture, "capture", capture)
    assert isolated.DesktopCaptureSource().capture(window) == "window-result"
    capture.assert_called_once_with(window)


def test_primary_worker_does_not_construct_window_capture_backend(monkeypatch):
    connection = Mock()
    primary_backend = Mock()
    primary_backend.capture.return_value = "primary-frame"
    monkeypatch.setattr(isolated, "PrimaryScreenCapture", Mock(return_value=primary_backend))
    windows_backend = Mock(side_effect=AssertionError("No window API for primary capture"))
    monkeypatch.setattr(isolated, "WindowsCapture", windows_backend)
    isolated._capture_worker(connection, "primary", PRIMARY_SCREEN)
    primary_backend.capture.assert_called_once_with(PRIMARY_SCREEN)
    connection.send.assert_called_once_with(("ok", "primary-frame"))
    connection.close.assert_called_once()
    windows_backend.assert_not_called()
