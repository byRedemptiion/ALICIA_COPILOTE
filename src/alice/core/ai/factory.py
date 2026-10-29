"""Instancie le fournisseur choisi dans la configuration."""

from __future__ import annotations

from alice.core.ai.base import VisionModel
from alice.core.config import AISettings


def create_model(settings: AISettings) -> VisionModel:
    if settings.provider == "gemini":
        from alice.core.ai.providers.gemini import GeminiModel

        return GeminiModel(settings.gemini, settings.timeout_s)
    if settings.provider == "ollama":
        from alice.core.ai.providers.ollama import OllamaModel

        return OllamaModel(settings.ollama, settings.timeout_s)
    from alice.core.ai.providers.fake import FakeModel

    return FakeModel(delay_s=0.03)
