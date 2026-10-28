from typing import Protocol


class SpeechError(RuntimeError):
    """Erreur vocale nettoyée, affichable au joueur."""


class SpeechProvider(Protocol):
    def synthesize(self, text: str) -> bytes: ...
