import base64
import io
import json
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from alicia.ai.ollama_provider import (
    OllamaVisionProvider,
    validate_local_model,
    validate_ollama_url,
)
from alicia.core.models import AnalysisRequest, CapturedFrame, WindowInfo
from alicia.core.ports import AnalysisError, ConfigurationError


def settings(**overrides):
    values = {
        "ollama_url": "http://127.0.0.1:11434",
        "ai_model": "qwen2.5vl:7b",
        "api_timeout_seconds": 120,
        "image_max_edge": 256,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def analysis_request(png=None, question=" Que voit-on ? "):
    if png is None:
        image = Image.new("RGB", (1024, 512), "blue")
        output = io.BytesIO()
        image.save(output, format="PNG")
        png = output.getvalue()
    return AnalysisRequest(
        frame=CapturedFrame(
            png, 1024, 512, WindowInfo(12, "Test", 42), datetime.now(UTC), "local-capture"
        ),
        question=question,
    )


def transport_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)


def test_local_request_contains_exact_question_and_bounded_png():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"message": {"content": " Une interface est visible. "}})

    with transport_client(handle) as client:
        result = OllamaVisionProvider(settings(), client).analyze(analysis_request())
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "http://127.0.0.1:11434/api/chat"
    assert request.extensions["timeout"]["read"] == 120
    payload = json.loads(request.content)
    assert payload["model"] == "qwen2.5vl:7b"
    assert payload["messages"][0]["role"] == "system"
    assert "français" in payload["messages"][0]["content"]
    assert payload["messages"][1]["content"] == "Que voit-on ?"
    with Image.open(io.BytesIO(base64.b64decode(payload["messages"][1]["images"][0]))) as image:
        assert image.size == (256, 128)
    assert payload["stream"] is False
    assert payload["keep_alive"] == "2m"
    assert result.text == "Une interface est visible."
    assert result.capture_id == "local-capture"
    assert result.model == "qwen2.5vl:7b"
    assert result.elapsed_seconds >= 0


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:11434",
        "http://example.com",
        "http://127.0.0.2:11434",
        "http://localhost.example.com:11434",
        "http://127.0.0.1.example.com",
        "http://user:pass@localhost:11434",
        "http://localhost:11434/api",
        "http://localhost:11434?proxy=example.com",
        "http://localhost:11434#fragment",
        "http://localhost:0",
        "http://localhost:65536",
        "http://localhost:bad",
        "http://[::1",
        "file:///tmp/ollama",
    ],
)
def test_nonlocal_or_ambiguous_endpoints_are_rejected(url):
    with pytest.raises(ConfigurationError):
        OllamaVisionProvider(settings(ollama_url=url))


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:11434", "http://localhost:11434/", "http://[::1]:11434"],
)
def test_loopback_endpoints_are_supported(url):
    assert validate_ollama_url(url) == url.rstrip("/")


@pytest.mark.parametrize(
    "model",
    ["gpt-oss:120b-cloud", "cloud/model", "https://example.com/model", "a:tag:tag", "", "a model"],
)
def test_cloud_or_ambiguous_model_names_are_rejected(model):
    with pytest.raises(ConfigurationError):
        OllamaVisionProvider(settings(ai_model=model))


def test_normal_local_model_names_are_supported():
    assert validate_local_model("qwen2.5vl:7b") == "qwen2.5vl:7b"
    assert validate_local_model("namespace/model:7b-q4_K_M") == "namespace/model:7b-q4_K_M"


@pytest.mark.parametrize("model", ["gpt-oss:120b-cloud", "another-model", {}, ""])
def test_different_response_model_is_not_accepted(model):
    payload = {"model": model, "message": {"content": "Unexpected answer"}}
    with transport_client(lambda _: httpx.Response(200, json=payload)) as client:
        with pytest.raises(AnalysisError, match="modèle différent"):
            OllamaVisionProvider(settings(), client).analyze(analysis_request())


def test_matching_response_model_is_accepted():
    payload = {"model": "qwen2.5vl:7b", "message": {"content": "Known model answer"}}
    with transport_client(lambda _: httpx.Response(200, json=payload)) as client:
        assert (
            OllamaVisionProvider(settings(), client).analyze(analysis_request()).text
            == "Known model answer"
        )


@pytest.mark.parametrize("kind", ["timeout", "connection"])
def test_network_errors_are_sanitized_and_not_retried(kind):
    attempts = []

    def fail(request):
        attempts.append(request)
        exception = httpx.ReadTimeout if kind == "timeout" else httpx.ConnectError
        raise exception("private-question-secret", request=request)

    with transport_client(fail) as client, pytest.raises(AnalysisError) as error:
        OllamaVisionProvider(settings(), client).analyze(analysis_request())
    assert len(attempts) == 1
    assert "private-question-secret" not in str(error.value)


def test_redirects_are_not_followed_to_external_services():
    attempts = []

    def redirect(request):
        attempts.append(request)
        return httpx.Response(307, headers={"Location": "https://example.com/pay"})

    with transport_client(redirect) as client, pytest.raises(AnalysisError):
        OllamaVisionProvider(settings(), client).analyze(analysis_request())
    assert len(attempts) == 1


@pytest.mark.parametrize("status", [400, 404, 429, 500])
def test_server_errors_do_not_leak_response_body(status):
    def handle(request):
        return httpx.Response(status, json={"error": "private-text-secret"})

    with transport_client(handle) as client, pytest.raises(AnalysisError) as error:
        OllamaVisionProvider(settings(), client).analyze(analysis_request())
    assert "private-text-secret" not in str(error.value)
    if status == 404:
        assert "ollama pull" in str(error.value)


@pytest.mark.parametrize(
    "payload",
    [{}, [], {"message": None}, {"message": {"content": " "}}, {"message": {"content": 5}}],
)
def test_malformed_response_does_not_count_as_analysis(payload):
    with transport_client(lambda _: httpx.Response(200, json=payload)) as client:
        with pytest.raises(AnalysisError, match="aucun texte"):
            OllamaVisionProvider(settings(), client).analyze(analysis_request())


def test_invalid_json_is_sanitized():
    with transport_client(lambda _: httpx.Response(200, text="not-json-private")) as client:
        with pytest.raises(AnalysisError, match="aucun texte") as error:
            OllamaVisionProvider(settings(), client).analyze(analysis_request())
    assert "private" not in str(error.value)


@pytest.mark.parametrize(
    "analysis", [analysis_request(png=b"bad-image"), analysis_request(question=" ")]
)
def test_bad_input_never_leaves_the_application(analysis):
    attempts = []
    with transport_client(lambda incoming: attempts.append(incoming)) as client:
        with pytest.raises(AnalysisError):
            OllamaVisionProvider(settings(), client).analyze(analysis)
    assert attempts == []


def test_real_loopback_http_transport_ignores_inherited_proxies(monkeypatch):
    """Exercise transport and PNG exchange with a local fixture, not an AI model."""
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            received.append((self.path, json.loads(self.rfile.read(length))))
            result = json.dumps(
                {
                    "model": "qwen2.5vl:7b",
                    "message": {"content": "Réponse du serveur de test local"},
                    "done": True,
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)

        def log_message(self, format, *args):
            pass

    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    except PermissionError:
        pytest.skip("Sandbox does not permit binding a local test server")
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    try:
        address = f"http://127.0.0.1:{server.server_port}"
        result = OllamaVisionProvider(settings(ollama_url=address)).analyze(analysis_request())
        assert result.text == "Réponse du serveur de test local"
        assert len(received) == 1
        path, body = received[0]
        assert path == "/api/chat"
        with Image.open(io.BytesIO(base64.b64decode(body["messages"][1]["images"][0]))) as image:
            assert image.size == (256, 128)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
