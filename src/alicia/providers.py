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
    if settings.tts_provider == "kokoro":
        from alicia.audio.kokoro_speech import KokoroSpeechProvider, KokoroSpeechSettings

        return KokoroSpeechProvider(
            KokoroSpeechSettings(
                model_directory=settings.neural_model_directory,
                voice=settings.neural_voice,
                speed=settings.neural_speed,
            )
        )
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


def create_listener_factory(settings: Settings):
    if settings.stt_provider == "whisper":
        from functools import partial

        from alicia.audio.whisper_listening import WhisperListener

        return partial(WhisperListener, device=settings.whisper_device)
    if settings.stt_provider == "vosk":
        from alicia.audio.listening import LocalListener

        return LocalListener
    raise ConfigurationError("Fournisseur de reconnaissance inconnu ; aucune bascule automatique.")
