"""A narrow local command gate, independent of speech engines and the UI."""

from __future__ import annotations

import re
import unicodedata


def _words(text: str) -> tuple[str, ...]:
    if not isinstance(text, str):
        return ()
    folded = "".join(
        character
        for character in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(character)
    )
    return tuple(re.findall(r"[a-z0-9]+", folded))


def is_stop_command(text: str) -> bool:
    """Accept the addressed command, never a quote inside an ordinary sentence."""
    return _words(text) in {
        ("alicia", "stop"),
        ("alicia", "stop", "s", "il", "te", "plait"),
        ("alicia", "stop", "s", "il", "vous", "plait"),
    }


def speech_contains_stop_command(text: str) -> bool:
    """Avoid enabling barge-in while the assistant itself explains the command.

    This lexical protection is not acoustic echo cancellation. Headphones remain
    the most reliable way to keep the assistant's speech out of the microphone.
    """
    words = _words(text)
    return any(pair == ("alicia", "stop") for pair in zip(words, words[1:]))
