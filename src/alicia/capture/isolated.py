"""Bound native capture work with disposable spawned processes."""

from __future__ import annotations

import multiprocessing
import os
import sys
from math import isfinite
from multiprocessing.connection import Connection
from typing import Any

from alicia.capture.primary import PRIMARY_SCREEN, PrimaryScreenCapture
from alicia.capture.win32 import WindowsCapture
from alicia.core.models import CapturedFrame, WindowInfo
from alicia.core.ports import CaptureError, UnsupportedPlatformError


def _capture_worker(connection: Connection, operation: str, window: WindowInfo | None) -> None:
    """Top-level target so the Windows spawn context can import it safely."""
    try:
        if operation == "primary" and window is not None:
            result = PrimaryScreenCapture().capture(window)
        elif operation == "list":
            result = WindowsCapture().list_windows()
        elif operation == "capture" and window is not None:
            result = WindowsCapture().capture(window)
        else:
            raise CaptureError("Opération de capture invalide.")
        packet = ("ok", result)
    except UnsupportedPlatformError:
        packet = ("unsupported", "La capture de fenêtres nécessite Windows.")
    except CaptureError as error:
        # The native adapter's public errors contain no window titles or raw OS data.
        packet = ("capture_error", str(error))
    except Exception:
        packet = ("capture_error", "Le processus de capture a rencontré une erreur.")
    try:
        connection.send(packet)
    except (OSError, EOFError):
        # The caller may already have timed out or closed its receiving endpoint.
        pass
    finally:
        connection.close()


def _stop_process(process: Any, started: bool) -> None:
    if not started:
        process.close()
        return
    process.join(timeout=0.1)
    if process.is_alive():
        process.terminate()
        process.join(timeout=0.5)
    if process.is_alive():
        process.kill()
        process.join(timeout=0.5)
    if not process.is_alive():
        process.close()


class IsolatedWindowsCapture:
    """Keep a stuck PrintWindow call outside both the GUI and its worker threads."""

    def __init__(self, list_timeout: float = 5.0, capture_timeout: float = 12.0) -> None:
        if not all(isfinite(value) and value > 0 for value in (list_timeout, capture_timeout)):
            raise ValueError("Les délais de capture doivent être strictement positifs et finis.")
        self.list_timeout = list_timeout
        self.capture_timeout = capture_timeout

    def list_windows(self) -> list[WindowInfo]:
        result = self._run("list", None, self.list_timeout)
        if not isinstance(result, list) or not all(isinstance(item, WindowInfo) for item in result):
            raise CaptureError("Le processus de capture a retourné une liste invalide.")
        # The native adapter excludes the child PID; also exclude the actual GUI PID.
        return [window for window in result if window.process_id != os.getpid()]

    def capture(self, window: WindowInfo) -> CapturedFrame:
        result = self._run("capture", window, self.capture_timeout)
        if not isinstance(result, CapturedFrame):
            raise CaptureError("Le processus de capture a retourné une image invalide.")
        return result

    def _run(self, operation: str, window: WindowInfo | None, timeout: float) -> Any:
        if sys.platform != "win32":
            raise UnsupportedPlatformError("La capture de fenêtres nécessite Windows.")
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(
            target=_capture_worker,
            args=(sender, operation, window),
            name="alicia-capture",
            daemon=True,
        )
        started = False
        try:
            process.start()
            started = True
            sender.close()
            if not receiver.poll(timeout):
                raise CaptureError(
                    "Le délai de capture est dépassé. Vérifiez que la fenêtre répond "
                    "et essayez le mode fenêtré."
                )
            packet = receiver.recv()
            if not isinstance(packet, tuple) or len(packet) != 2:
                raise CaptureError("La réponse du processus de capture est invalide.")
            status, payload = packet
            if status == "unsupported":
                raise UnsupportedPlatformError("La capture de fenêtres nécessite Windows.")
            if status == "capture_error" and isinstance(payload, str):
                raise CaptureError(payload)
            if status != "ok":
                raise CaptureError("La réponse du processus de capture est invalide.")
            return payload
        except (OSError, EOFError, RuntimeError) as error:
            if isinstance(error, CaptureError):
                raise
            raise CaptureError("Le processus de capture est indisponible. Réessayez.") from None
        finally:
            receiver.close()
            sender.close()
            _stop_process(process, started)


class DesktopCaptureSource(IsolatedWindowsCapture):
    """Offer the primary display first while retaining optional window selection."""

    def list_windows(self) -> list[WindowInfo]:
        screens = PrimaryScreenCapture().list_windows()
        try:
            windows = super().list_windows()
        except CaptureError:
            # The primary display does not depend on enumerating individual windows.
            return screens
        return screens + [window for window in windows if window != PRIMARY_SCREEN]

    def capture(self, window: WindowInfo) -> CapturedFrame:
        if window == PRIMARY_SCREEN:
            result = self._run("primary", window, self.capture_timeout)
            if not isinstance(result, CapturedFrame):
                raise CaptureError("Le processus de capture a retourné une image invalide.")
            return result
        return super().capture(window)
