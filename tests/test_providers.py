import subprocess
import sys
from dataclasses import replace

import httpx
import pytest

from alicia.ai.ollama_provider import OllamaVisionProvider
from alicia.audio.windows_speech import WindowsSpeechProvider
from alicia.capture.demo import DemoCapture
from alicia.config import Settings
from alicia.core.models import AnalysisRequest
from alicia.core.ports import AnalysisError, ConfigurationError
from alicia.providers import create_speech_provider, create_vision_provider


def test_default_providers_are_local_without_key():
    settings = Settings()
    assert isinstance(create_vision_provider(settings), OllamaVisionProvider)
    assert isinstance(create_speech_provider(settings), WindowsSpeechProvider)


def test_local_import_and_construction_do_not_load_openai_sdk():
    script = (
        "import sys; from alicia.config import Settings; "
        "from alicia.providers import create_vision_provider, create_speech_provider; "
        "create_vision_provider(Settings()); create_speech_provider(Settings()); "
        "assert 'openai' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", script], check=True, timeout=10)


@pytest.mark.parametrize("field", ["ai_provider", "tts_provider"])
def test_unknown_provider_never_falls_back(field):
    settings = replace(Settings(), **{field: "unknown"})
    factory = create_vision_provider if field == "ai_provider" else create_speech_provider
    with pytest.raises(ConfigurationError, match="bascule"):
        factory(settings)


def test_ollama_connection_error_does_not_construct_openai(monkeypatch):
    def forbid(*args, **kwargs):
        pytest.fail("A paid client must never be created as fallback")

    monkeypatch.setattr("openai.OpenAI", forbid)
    provider = create_vision_provider(Settings())

    def fail(_request):
        raise httpx.ConnectError("offline")

    source = DemoCapture()
    provider._client = httpx.Client(transport=httpx.MockTransport(fail))
    try:
        with pytest.raises(AnalysisError, match="Ollama"):
            provider.analyze(AnalysisRequest(source.capture(source.window), "Question"))
    finally:
        provider._client.close()
