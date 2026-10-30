"""Instancie le fournisseur choisi dans la configuration."""

from __future__ import annotations

from alicia.core.ai.base import VisionModel
from alicia.core.config import AISettings


def create_model(settings: AISettings) -> VisionModel:
    if settings.provider == "gemini":
        from alicia.core.ai.providers.gemini import GeminiModel

        return GeminiModel(settings.gemini, settings.timeout_s)
    if settings.provider == "openai":
        from alicia.core.ai.providers.openai import OpenAIModel

        return OpenAIModel(settings.openai, settings.timeout_s)
    if settings.provider == "ollama":
        from alicia.core.ai.providers.ollama import OllamaModel

        return OllamaModel(settings.ollama, settings.timeout_s)
    from alicia.core.ai.providers.fake import FakeModel

    return FakeModel(delay_s=0.03)


def create_deep_model(settings: AISettings) -> VisionModel | None:
    """Le cerveau « réfléchi » (None s'il n'est pas choisi)."""
    from dataclasses import replace

    provider, model = settings.deep_provider, settings.deep_model
    if not provider:
        return None
    ai = replace(settings, provider=provider)
    if provider == "ollama":
        ai = replace(ai, ollama=replace(ai.ollama, model=model or "qwen3.8:27b"))
    elif provider == "gemini" and model:
        ai = replace(ai, gemini=replace(ai.gemini, model=model))
    elif provider == "openai":
        ai = replace(
            ai, openai=replace(ai.openai, model=model or ai.openai.model, reasoning_effort="medium")
        )
    return create_model(ai)


_DEEP = None


def wants_deep_thinking(question: str) -> bool:
    """Questions qui méritent le cerveau réfléchi : stratégie, build, analyse, plan…"""
    return deep_reason(question) is not None


def deep_reason(question: str) -> str | None:
    """Le mot qui fait passer la question au cerveau réfléchi (pour les journaux), ou None."""
    import re
    import unicodedata

    global _DEEP
    if _DEEP is None:
        _DEEP = re.compile(
            r"\b(?:reflechis|reflechir|analyse|analyser|strategie|strategique|build|plan|"
            r"planifie|optimise|optimiser|compare|comparer|explique en detail|en detail|"
            r"pourquoi|meilleure? (?:facon|strategie|option|combo|rotation)|que dois-je faire|"
            r"comment battre|comment gagner|prochaines? minutes?|toute ma partie)\b"
        )
    plain = unicodedata.normalize("NFKD", question.casefold())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    match = _DEEP.search(plain)
    return match.group(0) if match else None
