"""CaptureService : seul point d'entrée de la capture pour le reste d'Alice."""

from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from alice.core.capture.backends import (
    DEMO_WINDOW,
    CaptureBackend,
    DemoBackend,
    PrintWindowBackend,
    WgcBackend,
)
from alice.core.capture.models import Frame, WindowInfo, image_from_bgra, is_black
from alice.core.config import CaptureSettings
from alice.core.errors import AliceError, CaptureError

log = logging.getLogger("alice.capture")


class CaptureService:
    """Liste les fenêtres et capture celle choisie en essayant les backends dans l'ordre.

    Chaque repli est journalisé et noté dans la ``Frame`` : rien n'est silencieux.
    """

    def __init__(
        self,
        lister: Callable[[], list[WindowInfo]],
        refresher: Callable[[WindowInfo], WindowInfo],
        chain: Callable[[WindowInfo], Sequence[CaptureBackend]],
        keep_last: int = 5,
        foreground: Callable[[], WindowInfo | None] | None = None,
    ) -> None:
        self._foreground = foreground
        self._lister = lister
        self._refresher = refresher
        self._chain = chain
        self.recent: deque[Frame] = deque(maxlen=keep_last)

    # --- fabriques ----------------------------------------------------------------------------

    @classmethod
    def for_windows(cls, settings: CaptureSettings) -> CaptureService:
        from alice.core.capture.win32 import Win32

        win32 = Win32()

        def chain(window: WindowInfo) -> list[CaptureBackend]:
            if settings.backend == "printwindow":
                return [PrintWindowBackend(win32)]
            backends: list[CaptureBackend] = [WgcBackend("window", settings.timeout_s)]
            if settings.monitor_fallback and window.fullscreen:
                backends.append(WgcBackend("monitor", settings.timeout_s))
            if settings.backend == "auto":
                backends.append(PrintWindowBackend(win32))
            return backends

        return cls(
            win32.list_windows,
            win32.check_still_valid,
            chain,
            settings.keep_last_frames,
            foreground=win32.foreground_window,
        )

    @classmethod
    def demo(cls, keep_last: int = 5) -> CaptureService:
        return cls(lambda: [DEMO_WINDOW], lambda w: w, lambda w: [DemoBackend()], keep_last)

    # --- opérations ---------------------------------------------------------------------------

    def list_windows(self) -> list[WindowInfo]:
        started = time.perf_counter()
        windows = self._lister()
        log.debug("%d fenêtres listées en %d ms", len(windows), _ms(started))
        return windows

    def foreground_window(self) -> WindowInfo | None:
        """Fenêtre active (hors Alice), ou None si inconnue."""
        if self._foreground is None:
            return None
        try:
            return self._foreground()
        except Exception as exc:  # noqa: BLE001
            log.warning("Fenêtre active introuvable : %r", exc)
            return None

    def capture(self, window: WindowInfo) -> Frame:
        started = time.perf_counter()
        try:
            window = self._refresher(window)
        except AliceError as exc:
            log.error("Capture refusée pour « %s » : %s", window.title, exc.detail)
            raise
        attempts: list[str] = []
        notes: list[str] = []
        for backend in self._chain(window):
            step = time.perf_counter()
            try:
                pixels = backend.grab(window)
            except AliceError as exc:
                attempts.append(f"{backend.name}: {exc.detail}")
                log.warning("Capture %s échouée : %s", backend.name, exc.detail)
                continue
            except Exception as exc:  # noqa: BLE001 - erreur native inattendue
                attempts.append(f"{backend.name}: {exc!r}")
                log.warning("Capture %s : erreur inattendue %r", backend.name, exc)
                continue
            if is_black(pixels):
                attempts.append(f"{backend.name}: image noire")
                log.warning("Capture %s : image entièrement noire, essai suivant", backend.name)
                continue
            if attempts:
                notes.append("Repli après : " + " ; ".join(attempts))
            frame = Frame(
                image=image_from_bgra(pixels),
                window=window,
                backend=backend.name,
                captured_at=datetime.now(UTC),
                duration_ms=_ms(started),
                capture_id=uuid.uuid4().hex[:6],
                notes=tuple(notes),
            )
            self.recent.append(frame)
            log.info(
                "Capture ok via %s : %dx%d en %d ms (grab %d ms)%s",
                backend.name,
                frame.width,
                frame.height,
                frame.duration_ms,
                _ms(step),
                " — " + notes[0] if notes else "",
            )
            return frame

        log.error("Capture impossible de « %s » : %s", window.title, " | ".join(attempts))
        hint = (
            " Le jeu est en plein écran : vérifie qu'il est bien sur l'écran affiché."
            if window.fullscreen
            else " Essaie le mode plein écran fenêtré du jeu."
        )
        raise CaptureError(
            "Impossible de capturer cette fenêtre (image noire ou refusée)." + hint,
            detail=" | ".join(attempts) or "aucun backend disponible",
        )

    @property
    def last(self) -> Frame | None:
        return self.recent[-1] if self.recent else None


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
