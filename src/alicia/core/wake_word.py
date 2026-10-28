"""Small local gate for final transcriptions; no audio or network dependency."""

from __future__ import annotations

import math
import re
import time
import unicodedata
from collections.abc import Callable


def _fold_with_offsets(value: str) -> tuple[str, list[int]]:
    folded = []
    offsets = []
    for index, character in enumerate(value):
        for part in unicodedata.normalize("NFKD", character.casefold()):
            if not unicodedata.combining(part):
                folded.append(part)
                offsets.append(index + 1)
    return "".join(folded), offsets


class WakeWordGate:
    def __init__(
        self,
        word: str = "Alicia",
        timeout_seconds: float = 8,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        folded, _ = _fold_with_offsets(word.strip())
        if not folded or not folded.isalpha():
            raise ValueError("Le mot d’activation doit contenir uniquement des lettres.")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Le délai d’activation doit être positif et fini.")
        self.word = word.strip()
        self.timeout_seconds = timeout_seconds
        self.clock = clock
        self._pattern = re.compile(r"(?<!\w)" + re.escape(folded) + r"(?!\w)")
        self._armed_until: float | None = None

    @property
    def armed(self) -> bool:
        if self._armed_until is not None and self.clock() >= self._armed_until:
            self.reset()
        return self._armed_until is not None

    def reset(self) -> None:
        self._armed_until = None

    def feed(self, text: str) -> str | None:
        if not isinstance(text, str) or not text.strip():
            return None
        folded, offsets = _fold_with_offsets(text)
        match = self._pattern.search(folded)
        if match is not None:
            end = offsets[match.end() - 1]
            while end < len(text) and unicodedata.combining(text[end]):
                end += 1
            suffix = text[end:].lstrip(" \t\r\n,;:!?.…—-").strip()
            self.reset()
            if suffix:
                return suffix
            self._armed_until = self.clock() + self.timeout_seconds
            return None
        if self.armed:
            self.reset()
            return text.strip()
        return None
