import base64
import io
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import APITimeoutError, AuthenticationError, RateLimitError
from PIL import Image

from alicia.ai.openai_provider import OpenAIVisionProvider
from alicia.config import Settings
from alicia.core.models import AnalysisRequest, CapturedFrame, WindowInfo
from alicia.core.ports import AnalysisError, ConfigurationError


def make_request(size=(40, 20), png=None):
    if png is None:
        output = io.BytesIO()
        Image.new("RGB", size, "blue").save(output, format="PNG")
        png = output.getvalue()
    frame = CapturedFrame(
        png=png,
        width=size[0],
        height=size[1],
        window=WindowInfo(handle=12, title="Test", process_id=42),
        captured_at=datetime.now(timezone.utc),
        capture_id="capture-test",
    )
    return AnalysisRequest(frame=frame, question=" Que voit-on ? ")


def fake_client(text="Une interface est visible."):
    return SimpleNamespace(
        responses=SimpleNamespace(create=Mock(return_value=SimpleNamespace(output_text=text)))
    )


def test_one_request_contains_question_and_bounded_image():
    client = fake_client()
    provider = OpenAIVisionProvider(Settings(api_key="test-secret", image_max_edge=256), client)
    result = provider.analyze(make_request(size=(1024, 512)))
    client.responses.create.assert_called_once()
    sent = client.responses.create.call_args.kwargs
    assert sent["store"] is False
    assert sent["input"][0]["content"][0]["text"] == "Que voit-on ?"
    url = sent["input"][0]["content"][1]["image_url"]
    with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as image:
        assert image.size == (256, 128)
    assert result.capture_id == "capture-test"
    assert result.text == "Une interface est visible."
    assert result.elapsed_seconds >= 0


def test_no_key_does_not_call_provider():
    client = fake_client()
    with pytest.raises(ConfigurationError):
        OpenAIVisionProvider(Settings(), client).analyze(make_request())
    client.responses.create.assert_not_called()


def test_corrupt_image_is_not_sent():
    client = fake_client()
    with pytest.raises(AnalysisError, match="capture"):
        OpenAIVisionProvider(Settings(api_key="test-secret"), client).analyze(
            make_request(png=b"not PNG")
        )
    client.responses.create.assert_not_called()


@pytest.mark.parametrize("text", ["", "   ", None])
def test_empty_response_is_not_success(text):
    with pytest.raises(AnalysisError, match="aucun texte"):
        OpenAIVisionProvider(Settings(api_key="test-secret"), fake_client(text)).analyze(
            make_request()
        )


@pytest.mark.parametrize("error_kind", ["authentication", "quota", "timeout"])
def test_errors_are_sanitized_and_never_retried(error_kind):
    client = fake_client()
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    if error_kind == "timeout":
        error = APITimeoutError(request=request)
    else:
        response = httpx.Response(401 if error_kind == "authentication" else 429, request=request)
        error_type = AuthenticationError if error_kind == "authentication" else RateLimitError
        error = error_type("private-error-secret", response=response, body=None)
    client.responses.create.side_effect = error
    with pytest.raises(AnalysisError) as caught:
        OpenAIVisionProvider(Settings(api_key="test-secret"), client).analyze(make_request())
    assert "private-error-secret" not in str(caught.value)
    client.responses.create.assert_called_once()
