"""Read-only capture of the visible Windows primary display."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4

from PIL import ImageGrab

from alicia.core.models import CapturedFrame, WindowInfo
from alicia.core.ports import CaptureError, UnsupportedPlatformError

PRIMARY_SCREEN = WindowInfo(handle=-1, title="Écran principal", process_id=0)
_MAX_PIXELS = 64 * 1024 * 1024


class _PrimaryAPI:
    def __init__(self):
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        self.user32.GetSystemMetrics.restype = ctypes.c_int
        set_dpi = getattr(self.user32, "SetProcessDpiAwarenessContext", None)
        if set_dpi is not None:
            set_dpi.argtypes = [wintypes.HANDLE]
            set_dpi.restype = wintypes.BOOL
            configured = set_dpi(ctypes.c_void_p(-4))
        else:
            configured = False
        if not configured:
            fallback = getattr(self.user32, "SetProcessDPIAware", None)
            if fallback is not None:
                fallback.argtypes = []
                fallback.restype = wintypes.BOOL
                fallback()

    def dimensions(self):
        # A DPI-aware process receives physical dimensions. Windows positions the
        # primary monitor at (0, 0), even with monitors to its left or above.
        return self.user32.GetSystemMetrics(0), self.user32.GetSystemMetrics(1)


class PrimaryScreenCapture:
    """Capture what is visible on the primary screen, including other applications."""

    def __init__(self):
        self._api: _PrimaryAPI | None = None

    @staticmethod
    def _require_windows():
        if sys.platform != "win32":
            raise UnsupportedPlatformError("La capture de l’écran principal nécessite Windows.")

    def list_windows(self) -> list[WindowInfo]:
        self._require_windows()
        return [PRIMARY_SCREEN]

    def capture(self, window: WindowInfo) -> CapturedFrame:
        self._require_windows()
        if window != PRIMARY_SCREEN:
            raise CaptureError("La source sélectionnée n’est pas l’écran principal.")
        try:
            if self._api is None:
                self._api = _PrimaryAPI()
            width, height = self._api.dimensions()
            if width <= 0 or height <= 0 or width * height > _MAX_PIXELS:
                raise CaptureError(
                    "Les dimensions de l’écran principal sont invalides ou trop grandes."
                )
            with ImageGrab.grab(
                bbox=(0, 0, width, height),
                all_screens=True,
                include_layered_windows=True,
            ) as image:
                if image.size != (width, height):
                    raise CaptureError(
                        "La capture ne correspond pas aux dimensions de l’écran principal."
                    )
                output = BytesIO()
                image.convert("RGB").save(output, format="PNG")
            return CapturedFrame(
                png=output.getvalue(),
                width=width,
                height=height,
                window=PRIMARY_SCREEN,
                captured_at=datetime.now(UTC),
                capture_id=uuid4().hex,
            )
        except CaptureError:
            raise
        except (OSError, RuntimeError, ValueError):
            raise CaptureError(
                "Impossible de capturer l’écran principal. Vérifiez que la session Windows est ouverte."
            ) from None
