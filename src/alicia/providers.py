"""Sélection explicite des fournisseurs ; aucune bascule automatique vers le cloud."""

from alicia.config import Settings
from alicia.core.ports import ConfigurationError


def create_vision_provider(settings: Settings):
    if settings.ai_provider == "ollama":
        from alicia.ai.ollama_provider import OllamaVisionProvider

        return OllamaVisionProvider(settings)
    if settings.ai_provider == "openai":
        from alicia.ai.openai_provider import OpenAIVisionProvider

        return OpenAIVisionProvider(settings)
    raise ConfigurationError("Fournisseur IA inconnu ; aucune bascule automatique.")


def create_speech_provider(settings: Settings):
    if settings.tts_provider == "windows":
        from alicia.audio.windows_speech import WindowsSpeechProvider

        return WindowsSpeechProvider(
            voice_name=settings.windows_voice,
            rate=settings.windows_rate,
            timeout_seconds=min(settings.api_timeout_seconds, 120),
        )
    if settings.tts_provider == "openai":
        from alicia.audio.openai_speech import OpenAISpeechProvider, SpeechSettings

        return OpenAISpeechProvider(
            SpeechSettings(
                api_key=settings.api_key,
                model=settings.tts_model,
                voice=settings.tts_voice,
                timeout_seconds=settings.api_timeout_seconds,
            )
        )
    raise ConfigurationError("Fournisseur vocal inconnu ; aucune bascule automatique.")
