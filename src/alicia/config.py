"""Local configuration; credentials are never included in its representation."""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from alicia.core.ports import ConfigurationError


def _default_log_directory() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return root / "Alicia" / "logs"
    root = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return root / "alicia" / "logs"


def default_voice_model_path() -> Path:
    return _default_log_directory().parent / "models" / "vosk-model-small-fr-0.22"


def default_neural_model_directory() -> Path:
    return _default_log_directory().parent / "models" / "kokoro"


def default_whisper_model_path() -> Path:
    return _default_log_directory().parent / "models" / "faster-whisper-small"


@dataclass(frozen=True, slots=True)
class Settings:
    ai_provider: str = "ollama"
    ai_model: str = "qwen2.5vl:7b"
    ollama_url: str = "http://127.0.0.1:11434"
    api_key: str | None = field(default=None, repr=False)
    api_timeout_seconds: float = 120.0
    image_max_edge: int = 1600
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "shimmer"
    tts_provider: str = "kokoro"
    stt_provider: str = "whisper"
    whisper_device: str = "cpu"
    neural_model_directory: Path = field(default_factory=default_neural_model_directory)
    neural_voice: str = "ff_siwis"
    neural_speed: float = 0.95
    whisper_model_path: Path = field(default_factory=default_whisper_model_path)
    windows_voice: str = ""
    windows_rate: int = -1
    voice_model_path: Path = field(default_factory=default_voice_model_path)
    capture_interval_ms: int = 1000
    log_directory: Path = field(default_factory=_default_log_directory)


def load_settings(env_file: Path | None = Path(".env")) -> Settings:
    """Read optional local settings without overriding injected environment values."""
    if env_file is not None:
        load_dotenv(dotenv_path=env_file, override=False)
    provider = os.environ.get("ALICIA_AI_PROVIDER", "ollama").strip().lower()
    if provider not in {"ollama", "openai"}:
        raise ConfigurationError("ALICIA_AI_PROVIDER doit être ollama ou openai.")
    model_variable = "ALICIA_OLLAMA_MODEL" if provider == "ollama" else "ALICIA_AI_MODEL"
    model_default = "qwen2.5vl:7b" if provider == "ollama" else "gpt-4.1-mini"
    model = os.environ.get(model_variable, model_default).strip()
    if not model:
        raise ConfigurationError(f"{model_variable} doit désigner un modèle multimodal.")
    tts_provider = os.environ.get("ALICIA_TTS_PROVIDER", "kokoro").strip().lower()
    if tts_provider not in {"kokoro", "windows", "openai"}:
        raise ConfigurationError("ALICIA_TTS_PROVIDER doit être kokoro, windows ou openai.")
    stt_provider = os.environ.get("ALICIA_STT_PROVIDER", "whisper").strip().lower()
    if stt_provider not in {"whisper", "vosk"}:
        raise ConfigurationError("ALICIA_STT_PROVIDER doit être whisper ou vosk.")
    whisper_device = os.environ.get("ALICIA_WHISPER_DEVICE", "cpu").strip().lower()
    if whisper_device not in {"cpu", "cuda"}:
        raise ConfigurationError("ALICIA_WHISPER_DEVICE doit être cpu ou cuda.")
    neural_voice = os.environ.get("ALICIA_NEURAL_VOICE", "ff_siwis").strip()
    if neural_voice != "ff_siwis":
        raise ConfigurationError(
            "ALICIA_NEURAL_VOICE doit être ff_siwis pour la voix française féminine."
        )
    try:
        neural_speed = float(os.environ.get("ALICIA_NEURAL_SPEED", "0.95"))
    except ValueError:
        raise ConfigurationError("ALICIA_NEURAL_SPEED doit être entre 0.7 et 1.3.") from None
    if not math.isfinite(neural_speed) or not 0.7 <= neural_speed <= 1.3:
        raise ConfigurationError("ALICIA_NEURAL_SPEED doit être entre 0.7 et 1.3.")
    try:
        windows_rate = int(os.environ.get("ALICIA_WINDOWS_RATE", "-1"))
    except ValueError:
        raise ConfigurationError(
            "ALICIA_WINDOWS_RATE doit être un entier entre -10 et 10."
        ) from None
    if not -10 <= windows_rate <= 10:
        raise ConfigurationError("ALICIA_WINDOWS_RATE doit être un entier entre -10 et 10.")
    tts_model = os.environ.get("ALICIA_TTS_MODEL", "gpt-4o-mini-tts").strip()
    if not tts_model:
        raise ConfigurationError("ALICIA_TTS_MODEL doit désigner un modèle de synthèse vocale.")
    tts_voice = os.environ.get("ALICIA_TTS_VOICE", "shimmer").strip()
    if not tts_voice:
        raise ConfigurationError("ALICIA_TTS_VOICE doit désigner une voix de synthèse.")
    try:
        timeout = float(
            os.environ.get("ALICIA_API_TIMEOUT_SECONDS", "120" if provider == "ollama" else "45")
        )
    except ValueError:
        raise ConfigurationError(
            "ALICIA_API_TIMEOUT_SECONDS doit être un nombre entre 1 et 120."
        ) from None
    if not math.isfinite(timeout) or not 1 <= timeout <= 120:
        raise ConfigurationError("ALICIA_API_TIMEOUT_SECONDS doit être un nombre entre 1 et 120.")
    try:
        max_edge = int(os.environ.get("ALICIA_IMAGE_MAX_EDGE", "1600"))
    except ValueError:
        raise ConfigurationError(
            "ALICIA_IMAGE_MAX_EDGE doit être un entier entre 256 et 4096."
        ) from None
    if not 256 <= max_edge <= 4096:
        raise ConfigurationError("ALICIA_IMAGE_MAX_EDGE doit être un entier entre 256 et 4096.")
    api_key = os.environ.get("OPENAI_API_KEY", "").strip() or None
    try:
        capture_interval = int(os.environ.get("ALICIA_CAPTURE_INTERVAL_MS", "1000"))
    except ValueError:
        raise ConfigurationError(
            "ALICIA_CAPTURE_INTERVAL_MS doit être entre 500 et 10000."
        ) from None
    if not 500 <= capture_interval <= 10000:
        raise ConfigurationError("ALICIA_CAPTURE_INTERVAL_MS doit être entre 500 et 10000.")
    return Settings(
        ai_provider=provider,
        ai_model=model,
        ollama_url=os.environ.get("ALICIA_OLLAMA_URL", "http://127.0.0.1:11434").strip(),
        api_key=api_key,
        api_timeout_seconds=timeout,
        image_max_edge=max_edge,
        tts_model=tts_model,
        tts_voice=tts_voice,
        tts_provider=tts_provider,
        stt_provider=stt_provider,
        whisper_device=whisper_device,
        neural_voice=neural_voice,
        neural_speed=neural_speed,
        neural_model_directory=Path(
            os.environ.get("ALICIA_NEURAL_MODEL_DIR") or default_neural_model_directory()
        ),
        whisper_model_path=Path(
            os.environ.get("ALICIA_WHISPER_MODEL_PATH") or default_whisper_model_path()
        ),
        windows_voice=os.environ.get("ALICIA_WINDOWS_VOICE", "").strip(),
        windows_rate=windows_rate,
        voice_model_path=Path(
            os.environ.get("ALICIA_VOICE_MODEL_PATH") or default_voice_model_path()
        ),
        capture_interval_ms=capture_interval,
    )
