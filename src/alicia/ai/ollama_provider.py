"""Explicit screenshot analysis through a loopback-only Ollama server."""

from __future__ import annotations

import base64
import io
import logging
import re
import time
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

import httpx
from PIL import Image, UnidentifiedImageError

from alicia.ai.conversation_context import conversation_messages
from alicia.ai.prompts import SYSTEM_PROMPT
from alicia.ai.web_context import MAX_WEB_SOURCES, format_web_context
from alicia.core.models import AnalysisRequest, AnalysisResult
from alicia.core.ports import AnalysisError, ConfigurationError

if TYPE_CHECKING:
    from alicia.config import Settings

logger = logging.getLogger("alicia.ai.local")


def validate_local_model(value: str) -> str:
    if (
        not isinstance(value, str)
        or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)*(?::[A-Za-z0-9][A-Za-z0-9_.-]*)?",
            value,
        )
        or "cloud" in value.casefold()
    ):
        raise ConfigurationError(
            "ALICIA_OLLAMA_MODEL doit désigner un modèle Ollama local, sans URL ni variante cloud."
        )
    return value


def validate_ollama_url(value: str) -> str:
    """Require a local HTTP endpoint; never forward captures to another host."""
    try:
        parsed = urlsplit(value)
        port = parsed.port
        hostname = parsed.hostname
    except (TypeError, ValueError):
        raise ConfigurationError(
            "ALICIA_OLLAMA_URL doit désigner le serveur Ollama local."
        ) from None
    if (
        parsed.scheme != "http"
        or hostname not in {"127.0.0.1", "::1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ConfigurationError(
            "ALICIA_OLLAMA_URL doit être une adresse HTTP locale, "
            "par exemple http://127.0.0.1:11434, sans chemin ni identifiants."
        )
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _image_base64(png: bytes, max_edge: int) -> str:
    try:
        with Image.open(io.BytesIO(png)) as source:
            source.load()
            image = source.convert("RGB")
            image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="PNG")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise AnalysisError("La capture est illisible ; effectuez une nouvelle capture.") from None
    return base64.b64encode(output.getvalue()).decode("ascii")


class OllamaVisionProvider:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.base_url = validate_ollama_url(settings.ollama_url)
        validate_local_model(settings.ai_model)
        self._client = client

    def analyze(self, request: AnalysisRequest) -> AnalysisResult:
        question = request.question.strip()
        if not question:
            raise AnalysisError("Saisissez une question avant de lancer l’analyse.")
        image = _image_base64(request.frame.png, self.settings.image_max_edge)
        sources = tuple(request.web_sources[:MAX_WEB_SOURCES])
        context = format_web_context(sources)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(conversation_messages(request.history))
        if context:
            messages.append({"role": "user", "content": context})
        messages.append({"role": "user", "content": question, "images": [image]})
        payload = {
            "model": self.settings.ai_model,
            "messages": messages,
            "stream": False,
            "keep_alive": "2m",
            "options": {"num_predict": 1200, "temperature": 0.2},
        }
        started = time.monotonic()
        logger.info("local_analysis_started capture_id=%s", request.frame.capture_id)
        # A fresh owned client makes cleanup deterministic. Proxies and redirects are
        # disabled so captures cannot leave loopback through the machine's settings.
        client = self._client or httpx.Client(trust_env=False, follow_redirects=False)
        try:
            response = client.post(
                self.base_url + "/api/chat",
                json=payload,
                timeout=self.settings.api_timeout_seconds,
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            self._failure("timeout")
            raise AnalysisError(
                "L’analyse locale a dépassé le délai maximal. Le premier chargement "
                "du modèle peut être long ; vérifiez Ollama puis réessayez."
            ) from None
        except httpx.HTTPError:
            self._failure("connection")
            raise AnalysisError(
                "Ollama local est inaccessible. Lancez Ollama ou scripts/setup_local.ps1 "
                "sur votre PC, puis réessayez."
            ) from None
        finally:
            if self._client is None:
                client.close()

        if response.status_code == 404:
            self._failure("model_missing")
            raise AnalysisError(
                "Le modèle local est introuvable. Installez le modèle configuré avec "
                "ollama pull, ou lancez scripts/setup_local.ps1."
            )
        if not 200 <= response.status_code < 300:
            self._failure("server_error")
            raise AnalysisError(
                "Ollama n’a pas pu analyser l’image. Vérifiez que le modèle configuré "
                "accepte les images et que les ressources de votre PC sont disponibles."
            )
        try:
            result = response.json()
        except ValueError:
            result = None
        returned_model = result.get("model") if isinstance(result, dict) else None
        if returned_model is not None and returned_model != self.settings.ai_model:
            self._failure("unexpected_model")
            raise AnalysisError("Ollama a répondu avec un modèle différent de celui configuré.")
        message = result.get("message") if isinstance(result, dict) else None
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str) or not text.strip():
            self._failure("empty_response")
            raise AnalysisError("Ollama n’a retourné aucun texte exploitable.")
        elapsed = time.monotonic() - started
        logger.info(
            "local_analysis_completed capture_id=%s duration_seconds=%.3f",
            request.frame.capture_id,
            elapsed,
        )
        return AnalysisResult(
            text=text.strip(),
            model=self.settings.ai_model,
            elapsed_seconds=elapsed,
            capture_id=request.frame.capture_id,
            web_sources=sources,
        )

    @staticmethod
    def _failure(category: str) -> None:
        logger.warning("local_analysis_failed category=%s", category)
