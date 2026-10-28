import logging

import pytest

from alicia.config import load_settings
from alicia.core.ports import ConfigurationError
from alicia.logging_config import configure_logging


@pytest.fixture(autouse=True)
def clear_configuration(monkeypatch):
    for name in (
        "ALICIA_AI_MODEL",
        "ALICIA_AI_PROVIDER",
        "ALICIA_OLLAMA_MODEL",
        "ALICIA_OLLAMA_URL",
        "ALICIA_TTS_PROVIDER",
        "ALICIA_WINDOWS_RATE",
        "ALICIA_WINDOWS_VOICE",
        "ALICIA_API_TIMEOUT_SECONDS",
        "ALICIA_IMAGE_MAX_EDGE",
        "ALICIA_TTS_MODEL",
        "ALICIA_TTS_VOICE",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_no_key_uses_free_local_providers():
    settings = load_settings(env_file=None)
    assert settings.api_key is None
    assert settings.ai_provider == "ollama"
    assert settings.ai_model == "qwen2.5vl:7b"
    assert settings.api_timeout_seconds == 120
    assert settings.tts_provider == "windows"
    assert settings.windows_rate == -1
    assert settings.tts_model == "gpt-4o-mini-tts"
    assert settings.tts_voice == "shimmer"


def test_voice_configuration_uses_environment(monkeypatch):
    monkeypatch.setenv("ALICIA_TTS_MODEL", "custom-tts-model")
    monkeypatch.setenv("ALICIA_TTS_VOICE", "custom-voice")
    settings = load_settings(env_file=None)
    assert settings.tts_model == "custom-tts-model"
    assert settings.tts_voice == "custom-voice"


def test_dotenv_does_not_override_injected_configuration(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "ALICIA_OLLAMA_MODEL=file-model\nOPENAI_API_KEY=local-test-secret\n", encoding="utf-8"
    )
    monkeypatch.setenv("ALICIA_OLLAMA_MODEL", "injected-model")
    settings = load_settings(dotenv)
    assert settings.ai_model == "injected-model"
    assert settings.api_key == "local-test-secret"
    assert "local-test-secret" not in repr(settings)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.mark.parametrize(
    "name,value",
    [
        ("ALICIA_OLLAMA_MODEL", "  "),
        ("ALICIA_AI_PROVIDER", "unknown"),
        ("ALICIA_TTS_PROVIDER", "unknown"),
        ("ALICIA_WINDOWS_RATE", "fast"),
        ("ALICIA_WINDOWS_RATE", "11"),
        ("ALICIA_TTS_MODEL", "  "),
        ("ALICIA_TTS_VOICE", "  "),
        ("ALICIA_API_TIMEOUT_SECONDS", "NaN"),
        ("ALICIA_API_TIMEOUT_SECONDS", "inf"),
        ("ALICIA_API_TIMEOUT_SECONDS", "not-a-number"),
        ("ALICIA_API_TIMEOUT_SECONDS", "0"),
        ("ALICIA_API_TIMEOUT_SECONDS", "121"),
        ("ALICIA_IMAGE_MAX_EDGE", "bad"),
        ("ALICIA_IMAGE_MAX_EDGE", "255"),
        ("ALICIA_IMAGE_MAX_EDGE", "4097"),
    ],
)
def test_invalid_configuration_has_safe_error(name, value, monkeypatch):
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigurationError) as error:
        load_settings(env_file=None)
    assert name in str(error.value)
    assert "not-a-number" not in str(error.value)


def test_logging_is_repeatable_and_does_not_enable_sdk_debug(tmp_path):
    sdk = logging.getLogger("openai")
    before = sdk.level
    path = configure_logging(tmp_path, debug=True)
    configure_logging(tmp_path, debug=True)
    logger = logging.getLogger("alicia.config")
    logger.info("configuration_loaded")
    assert path == tmp_path / "alicia.log"
    assert path.read_text(encoding="utf-8").count("configuration_loaded") == 1
    assert sdk.level == before
    assert "Z INFO" in path.read_text(encoding="utf-8")


def test_logging_retention_is_bounded(tmp_path):
    configure_logging(tmp_path)
    logger = logging.getLogger("alicia")
    handler = next(item for item in logger.handlers if getattr(item, "_alicia_managed", False))
    assert handler.maxBytes == 2_000_000
    assert handler.backupCount == 3
    assert not logger.propagate


def test_old_openai_settings_do_not_enable_paid_calls(monkeypatch):
    monkeypatch.setenv("ALICIA_AI_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("ALICIA_TTS_MODEL", "gpt-4o-mini-tts")
    monkeypatch.setenv("OPENAI_API_KEY", "old-test-key")
    settings = load_settings(env_file=None)
    assert settings.ai_provider == "ollama"
    assert settings.ai_model == "qwen2.5vl:7b"
    assert settings.tts_provider == "windows"


def test_openai_requires_explicit_provider_choice(monkeypatch):
    monkeypatch.setenv("ALICIA_AI_PROVIDER", "openai")
    monkeypatch.setenv("ALICIA_TTS_PROVIDER", "openai")
    settings = load_settings(env_file=None)
    assert settings.ai_model == "gpt-4.1-mini"
    assert settings.api_timeout_seconds == 45
