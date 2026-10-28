"""Read-only Windows client-area capture, without input or process injection."""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

from PIL import Image

from alicia.core.models import CapturedFrame, WindowInfo
from alicia.core.ports import CaptureError, UnsupportedPlatformError

_PW_CLIENTONLY = 0x00000001
_PW_RENDERFULLCONTENT = 0x00000002
_MAX_PIXELS = 64 * 1024 * 1024
_HGDI_ERROR = ctypes.c_void_p(-1).value


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [("bmiHeader", _BitmapInfoHeader), ("bmiColors", wintypes.DWORD * 1)]


class _WindowsAPI:
    def __init__(self) -> None:
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self.enum_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        specifications = [
            (self.user32.EnumWindows, [self.enum_callback, wintypes.LPARAM], wintypes.BOOL),
            (self.user32.IsWindow, [wintypes.HWND], wintypes.BOOL),
            (self.user32.IsWindowVisible, [wintypes.HWND], wintypes.BOOL),
            (self.user32.IsIconic, [wintypes.HWND], wintypes.BOOL),
            (self.user32.GetWindowTextLengthW, [wintypes.HWND], ctypes.c_int),
            (
                self.user32.GetWindowTextW,
                [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int],
                ctypes.c_int,
            ),
            (
                self.user32.GetWindowThreadProcessId,
                [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)],
                wintypes.DWORD,
            ),
            (
                self.user32.GetClientRect,
                [wintypes.HWND, ctypes.POINTER(wintypes.RECT)],
                wintypes.BOOL,
            ),
            (self.user32.GetDC, [wintypes.HWND], wintypes.HDC),
            (self.user32.ReleaseDC, [wintypes.HWND, wintypes.HDC], ctypes.c_int),
            (self.user32.PrintWindow, [wintypes.HWND, wintypes.HDC, wintypes.UINT], wintypes.BOOL),
            (self.gdi32.CreateCompatibleDC, [wintypes.HDC], wintypes.HDC),
            (self.gdi32.DeleteDC, [wintypes.HDC], wintypes.BOOL),
            (
                self.gdi32.CreateCompatibleBitmap,
                [wintypes.HDC, ctypes.c_int, ctypes.c_int],
                wintypes.HBITMAP,
            ),
            (self.gdi32.SelectObject, [wintypes.HDC, wintypes.HANDLE], wintypes.HANDLE),
            (self.gdi32.DeleteObject, [wintypes.HANDLE], wintypes.BOOL),
            (
                self.gdi32.GetDIBits,
                [
                    wintypes.HDC,
                    wintypes.HBITMAP,
                    wintypes.UINT,
                    wintypes.UINT,
                    ctypes.c_void_p,
                    ctypes.POINTER(_BitmapInfo),
                    wintypes.UINT,
                ],
                ctypes.c_int,
            ),
            (
                self.user32.SendMessageTimeoutW,
                [
                    wintypes.HWND,
                    wintypes.UINT,
                    wintypes.WPARAM,
                    wintypes.LPARAM,
                    wintypes.UINT,
                    wintypes.UINT,
                    ctypes.POINTER(ctypes.c_size_t),
                ],
                wintypes.LPARAM,
            ),
        ]
        for function, arguments, result in specifications:
            function.argtypes = arguments
            function.restype = result
        set_dpi = getattr(self.user32, "SetProcessDpiAwarenessContext", None)
        if set_dpi is not None:
            set_dpi.argtypes = [wintypes.HANDLE]
            set_dpi.restype = wintypes.BOOL
            # Windows may reject this when Qt already configured DPI awareness.
            set_dpi(ctypes.c_void_p(-4))

    def title(self, handle: int) -> str:
        length = self.user32.GetWindowTextLengthW(handle)
        buffer = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(handle, buffer, length + 1)
        return buffer.value

    def process_id(self, handle: int) -> int:
        process_id = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id))
        return process_id.value


def _png_from_bgra(pixels: bytes, width: int, height: int) -> bytes:
    image = Image.frombytes("RGB", (width, height), pixels, "raw", "BGRX")
    if all(high == 0 for _, high in image.getextrema()):
        raise CaptureError(
            "La capture est entièrement noire. Vérifiez l’aperçu du jeu et essayez "
            "le mode fenêtré ; cette image ne permet pas de confirmer une capture valide."
        )
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _capture_pixels(api: _WindowsAPI, handle: int, width: int, height: int) -> bytes:
    window_dc = None
    memory_dc = None
    bitmap = None
    previous = None
    selected = False
    try:
        window_dc = api.user32.GetDC(handle)
        if not window_dc:
            raise CaptureError("Impossible d’obtenir le contexte de la fenêtre.")
        memory_dc = api.gdi32.CreateCompatibleDC(window_dc)
        if not memory_dc:
            raise CaptureError("Impossible de créer le contexte de capture.")
        bitmap = api.gdi32.CreateCompatibleBitmap(window_dc, width, height)
        if not bitmap:
            raise CaptureError("Impossible d’allouer l’image de capture.")
        previous = api.gdi32.SelectObject(memory_dc, bitmap)
        if not previous or previous == _HGDI_ERROR:
            raise CaptureError("Impossible de préparer l’image de capture.")
        selected = True
        if not api.user32.PrintWindow(handle, memory_dc, _PW_CLIENTONLY | _PW_RENDERFULLCONTENT):
            raise CaptureError("La fenêtre ne fournit pas d’image via PrintWindow.")
        # GetDIBits requires the bitmap to be deselected from its device context.
        api.gdi32.SelectObject(memory_dc, previous)
        selected = False
        info = _BitmapInfo()
        info.bmiHeader.biSize = ctypes.sizeof(_BitmapInfoHeader)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        pixels = ctypes.create_string_buffer(width * height * 4)
        lines = api.gdi32.GetDIBits(memory_dc, bitmap, 0, height, pixels, ctypes.byref(info), 0)
        if lines != height:
            raise CaptureError("La lecture des pixels de la fenêtre a échoué.")
        return pixels.raw
    finally:
        if selected:
            api.gdi32.SelectObject(memory_dc, previous)
        if bitmap:
            api.gdi32.DeleteObject(bitmap)
        if memory_dc:
            api.gdi32.DeleteDC(memory_dc)
        if window_dc:
            api.user32.ReleaseDC(handle, window_dc)


class WindowsCapture:
    def __init__(self) -> None:
        self._api: _WindowsAPI | None = None

    def _require_api(self) -> _WindowsAPI:
        if sys.platform != "win32":
            raise UnsupportedPlatformError("La capture de fenêtres nécessite Windows.")
        if self._api is None:
            self._api = _WindowsAPI()
        return self._api

    def list_windows(self) -> list[WindowInfo]:
        api = self._require_api()
        windows: list[WindowInfo] = []

        @api.enum_callback
        def visit(handle: int, _parameter: int) -> bool:
            if api.user32.IsWindowVisible(handle):
                title = api.title(handle).strip()
                process_id = api.process_id(handle)
                if title and process_id and process_id != os.getpid():
                    windows.append(
                        WindowInfo(handle=int(handle), title=title, process_id=process_id)
                    )
            return True

        if not api.user32.EnumWindows(visit, 0):
            raise CaptureError("Impossible d’énumérer les fenêtres Windows.")
        return sorted(windows, key=lambda window: (window.title.casefold(), window.handle))

    def capture(self, window: WindowInfo) -> CapturedFrame:
        api = self._require_api()
        if not api.user32.IsWindow(window.handle):
            raise CaptureError("La fenêtre sélectionnée est fermée. Actualisez la liste.")
        if (
            api.process_id(window.handle) != window.process_id
            or api.title(window.handle).strip() != window.title
        ):
            raise CaptureError("La fenêtre sélectionnée a changé. Actualisez la liste.")
        if api.user32.IsIconic(window.handle):
            raise CaptureError("Restaurez la fenêtre minimisée avant la capture.")
        response = ctypes.c_size_t()
        if not api.user32.SendMessageTimeoutW(
            window.handle, 0, 0, 0, 0x0002, 500, ctypes.byref(response)
        ):
            raise CaptureError("La fenêtre ne répond pas. Réessayez après sa restauration.")
        rectangle = wintypes.RECT()
        if not api.user32.GetClientRect(window.handle, ctypes.byref(rectangle)):
            raise CaptureError("Impossible de lire les dimensions de la fenêtre.")
        width = rectangle.right - rectangle.left
        height = rectangle.bottom - rectangle.top
        if width <= 0 or height <= 0 or width * height > _MAX_PIXELS:
            raise CaptureError("Les dimensions de la fenêtre sont invalides ou trop grandes.")
        pixels = _capture_pixels(api, window.handle, width, height)
        return CapturedFrame(
            png=_png_from_bgra(pixels, width, height),
            width=width,
            height=height,
            window=window,
            captured_at=datetime.now(timezone.utc),
            capture_id=uuid4().hex,
        )
