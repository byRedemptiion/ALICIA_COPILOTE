import base64
import io
import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
from PIL import Image

from alicia.ai.ollama_provider import OllamaVisionProvider
from alicia.ai.openai_provider import OpenAIVisionProvider
from alicia.config import Settings
from alicia.core.models import (
    AnalysisRequest,
    CapturedFrame,
    ConversationTurn,
    WebSource,
    WindowInfo,
)


def request_with_history(history=None, web=False):
    output = io.BytesIO()
    Image.new("RGB", (32, 16), "green").save(output, format="PNG")
    frame = CapturedFrame(
        output.getvalue(), 32, 16, WindowInfo(1, "Écran", 0), datetime.now(UTC), "current-screen"
    )
    sources = (
        (
            WebSource(
                "Source actuelle",
                "https://example.com/current",
                "Extrait récent à vérifier.",
                datetime.now(UTC),
            ),
        )
        if web
        else ()
    )
    history = (
        history
        if history is not None
        else (ConversationTurn("Compare l’épée et la hache.", "L’épée est plus rapide [1]."),)
    )
    return AnalysisRequest(frame, "Et celui-là ?", web_sources=sources, history=history)


def assert_current_png(encoded):
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
        assert image.size == (32, 16)
        assert image.getpixel((0, 0)) == (0, 128, 0)


def test_ollama_gets_prior_turns_before_current_web_and_screen():
    request = request_with_history(web=True)
    payloads = []

    def handle(http_request):
        payloads.append(json.loads(http_request.content))
        return httpx.Response(
            200, json={"message": {"content": "Précisez quel objet vous désignez."}}
        )

    with httpx.Client(transport=httpx.MockTransport(handle), trust_env=False) as client:
        result = OllamaVisionProvider(Settings(), client).analyze(request)
    messages = payloads[0]["messages"]
    assert [item["role"] for item in messages] == ["system", "user", "assistant", "user", "user"]
    assert messages[1]["content"] == request.history[0].user
    assert messages[2]["content"] == request.history[0].assistant
    assert "images" not in messages[1] and "images" not in messages[2]
    assert "CONTEXTE_WEB_NON_FIABLE" in messages[3]["content"]
    assert messages[-1]["content"] == "Et celui-là ?"
    assert_current_png(messages[-1]["images"][0])
    assert result.capture_id == "current-screen"
    assert result.web_sources == request.web_sources


def test_openai_gets_same_short_context_without_persisting_it():
    request = request_with_history(web=True)
    create = Mock(return_value=SimpleNamespace(output_text="Quel objet désignez-vous ?"))
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    result = OpenAIVisionProvider(Settings(api_key="fixture-key"), client).analyze(request)
    sent = create.call_args.kwargs
    assert sent["store"] is False
    assert [item["role"] for item in sent["input"]] == ["user", "assistant", "user", "user"]
    assert sent["input"][0]["content"] == request.history[0].user
    assert sent["input"][1]["content"] == request.history[0].assistant
    current = sent["input"][-1]["content"]
    assert current[0]["text"] == "Et celui-là ?"
    assert_current_png(current[1]["image_url"].split(",", 1)[1])
    assert result.web_sources == request.web_sources


def test_external_request_history_remains_bounded_before_sending():
    history = tuple(
        ConversationTurn(f"Question {index} " + "Q" * 4000, "R" * 8000) for index in range(20)
    )
    request = request_with_history(history=history)
    create = Mock(return_value=SimpleNamespace(output_text="Réponse"))
    provider = OpenAIVisionProvider(
        Settings(api_key="fixture-key"), SimpleNamespace(responses=SimpleNamespace(create=create))
    )
    provider.analyze(request)
    old_messages = create.call_args.kwargs["input"][:-1]
    assert len(old_messages) <= 8
    assert sum(len(item["content"]) for item in old_messages) <= 6000
    assert old_messages[-2]["content"].startswith("Question 19")


def test_conversation_contents_are_not_written_to_logs(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="alicia")
    monkeypatch.setattr(logging.getLogger("alicia"), "propagate", True)
    request = request_with_history(
        history=(ConversationTurn("QUESTION_CONFIDENTIELLE", "REPONSE_CONFIDENTIELLE"),)
    )
    create = Mock(return_value=SimpleNamespace(output_text="RÉSULTAT_CONFIDENTIEL"))
    OpenAIVisionProvider(
        Settings(api_key="fixture-key"), SimpleNamespace(responses=SimpleNamespace(create=create))
    ).analyze(request)
    assert "analysis_started" in caplog.text
    assert "QUESTION_CONFIDENTIELLE" not in caplog.text
    assert "REPONSE_CONFIDENTIELLE" not in caplog.text
    assert "RÉSULTAT_CONFIDENTIEL" not in caplog.text
