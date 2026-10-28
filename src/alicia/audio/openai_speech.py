"""OpenAI speech adapter, with no microphone access or automatic playback."""

from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from alicia.audio.ports import SpeechError


@dataclass(frozen=True)
class SpeechSettings:
    api_key: str | None = field(repr=False)
    model: str = "gpt-4o-mini-tts"
    voice: str = "shimmer"
    timeout_seconds: float = 45


SOFT_VOICE_INSTRUCTIONS = (
    "Parle en français avec une voix féminine douce, calme et chaleureuse. "
    "Garde un rythme naturel, une diction claire et un ton posé, sans surjouer. "
    "Lis uniquement le texte fourni, sans ajouter de commentaire."
)


class OpenAISpeechProvider:
    """Generate a WAV only when explicitly requested by the application.

    Voice instructions are supported by gpt-4o-mini-tts, including dated
    variants, but not the older tts-1 models. The chosen voice and model remain
    configurable, and their actual availability depends on the API account.
    """

    def __init__(self, settings: SpeechSettings, client: Any = None) -> None:
        self.settings = settings
        self._client = client

    def synthesize(self, text: str) -> bytes:
        if not isinstance(text, str) or not text.strip():
            raise SpeechError("Aucun texte à lire.")
        if len(text) > 4096:
            raise SpeechError("La réponse dépasse 4 096 caractères ; réduisez le texte à lire.")
        if not self.settings.api_key:
            raise SpeechError("Configurez OPENAI_API_KEY pour activer la lecture vocale.")

        arguments = {
            "model": self.settings.model,
            "voice": self.settings.voice,
            "input": text,
            "response_format": "wav",
        }
        if self.settings.model.startswith("gpt-4o-mini-tts"):
            arguments["instructions"] = SOFT_VOICE_INSTRUCTIONS

        try:
            if self._client is None:
                self._client = OpenAI(
                    api_key=self.settings.api_key,
                    timeout=self.settings.timeout_seconds,
                    max_retries=0,
                )
            with self._client.audio.speech.with_streaming_response.create(**arguments) as response:
                audio = b"".join(response.iter_bytes())
        except Exception:
            # SDK exceptions may include request contents or credential details.
            raise SpeechError(
                "La génération vocale a échoué. Vérifiez la connexion, la clé "
                "et l’accès au modèle vocal configuré."
            ) from None

        if len(audio) < 12 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
            raise SpeechError("Le service vocal n’a pas renvoyé de fichier WAV valide.")
        return audio
