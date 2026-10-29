"""Vision en direct : ALICIA garde en mémoire une capture récente de l'écran.

Une capture est faite à intervalle régulier (1 s par défaut), selon le mode de vision.
Quand tu commences à parler (F10 ou « Alicia… »), l'image de cet instant est déjà prête :
pas d'attente de capture, et l'IA voit l'écran tel qu'il était quand tu as parlé.

Les images restent en mémoire (les 3 dernières) : rien n'est envoyé à l'IA ni enregistré
tant que tu ne poses pas de question.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from alicia.core.capture.models import Frame, WindowInfo
from alicia.core.errors import AliciaError

log = logging.getLogger("alicia.capture")

Target = Callable[[], tuple[WindowInfo | None, str, tuple[int, int]]]


class LiveCapture:
    def __init__(
        self,
        capture: Callable[[WindowInfo | None, str, tuple[int, int]], Frame],
        target: Target,
        interval_s: float = 1.0,
    ) -> None:
        self._capture = capture
        self._target = target
        self.interval_s = max(0.3, interval_s)
        self.latest: Frame | None = None
        self.latest_at = 0.0  # time.monotonic() de la dernière capture réussie
        self.frames = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._errors = 0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="alicia-live", daemon=True)
        self._thread.start()
        log.info("Vision en direct : une capture toutes les %.1f s (en mémoire)", self.interval_s)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2.0)
        self._thread = None
        log.info("Vision en direct coupée")

    def fresh(self, max_age_s: float = 3.0) -> Frame | None:
        """La dernière capture si elle a moins de ``max_age_s`` secondes."""
        if self.latest is None or time.monotonic() - self.latest_at > max_age_s:
            return None
        return self.latest

    def grab_once(self) -> Frame | None:
        window, mode, box = self._target()
        if mode == "window" and window is None:
            return None
        try:
            frame = self._capture(window, mode, box)
        except AliciaError as exc:
            self._errors += 1
            if self._errors in (1, 10) or self._errors % 100 == 0:
                log.warning("Vision en direct : capture impossible (%s)", exc.detail)
            return None
        self._errors = 0
        self.latest, self.latest_at = frame, time.monotonic()
        self.frames += 1
        return frame

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self.grab_once()
            except Exception:  # noqa: BLE001 - la vision en direct ne doit jamais planter ALICIA
                log.exception("Vision en direct : erreur inattendue")
            self._stop.wait(max(0.05, self.interval_s - (time.monotonic() - started)))
