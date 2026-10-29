"""Raccourci clavier global Windows (RegisterHotKey).

Alice est seulement *prévenue* de l'appui sur la touche : rien n'est envoyé au jeu.
La touche est réservée par Windows tant qu'Alice est ouverte (le jeu ne la reçoit plus).
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal

from alice.core.errors import ConfigError

log = logging.getLogger("alice.ui")

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
_MODIFIERS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT}


def parse_hotkey(text: str) -> tuple[int, int]:
    """« ctrl+F9 » → (modificateurs, code de touche virtuelle)."""
    parts = [p.strip().lower() for p in text.replace(" ", "").split("+") if p.strip()]
    if not parts:
        raise ConfigError("Raccourci vide.")
    modifiers = 0
    for part in parts[:-1]:
        if part not in _MODIFIERS:
            raise ConfigError(f"Modificateur inconnu « {part} » dans le raccourci « {text} ».")
        modifiers |= _MODIFIERS[part]
    key = parts[-1]
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    else:
        raise ConfigError(f"Touche « {key} » non prise en charge (F1-F24, lettre ou chiffre).")
    return modifiers, vk


class GlobalHotkey(QObject):
    pressed = Signal()
    failed = Signal(str)

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text
        self.modifiers, self.vk = parse_hotkey(text)
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self.active = False

    def start(self) -> bool:
        if sys.platform != "win32":
            return False
        self._thread = threading.Thread(target=self._loop, name="alice-hotkey", daemon=True)
        self._thread.start()
        self._ready.wait(2.0)
        return self.active

    def stop(self) -> None:
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(1.0)

    def _loop(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32")
        self._thread_id = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, 1, self.modifiers | MOD_NOREPEAT, self.vk):
            error = ctypes.get_last_error()
            message = (
                f"Le raccourci {self.text} est déjà utilisé par un autre programme "
                f"(code {error}). Change-le dans alice.toml ([hotkeys] analyze)."
            )
            log.error(message)
            self.failed.emit(message)
            self._ready.set()
            return
        self.active = True
        log.info("Raccourci global %s actif", self.text)
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    log.info("Raccourci %s pressé", self.text)
                    self.pressed.emit()
        finally:
            user32.UnregisterHotKey(None, 1)
            self.active = False
