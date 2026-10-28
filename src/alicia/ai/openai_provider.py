"""One explicitly requested screenshot analysis per provider call."""

from __future__ import annotations

import base64
import io
import logging
import time
from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)
from PIL import Image, UnidentifiedImageError

from alicia.ai.conversation_context import conversation_messages
from alicia.ai.prompts import SYSTEM_PROMPT
from alicia.ai.web_context import MAX_WEB_SOURCES, format_web_context
from alicia.config import Settings
from alicia.core.models import AnalysisRequest, AnalysisResult
from alicia.core.ports import AnalysisError, ConfigurationError

logger = logging.getLogger("alicia.ai")


def _image_data_url(png: bytes, max_edge: int) -> str:
    try:
        with Image.open(io.BytesIO(png)) as source:
            source.load()
            image = source.convert("RGB")
            image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="PNG")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise AnalysisError("La capture est illisible ; effectuez une nouvelle capture.") from None
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


class OpenAIVisionProvider:
    def __init__(self, settings: Settings, client: Any = None) -> None:
        self.settings = settings
        self._client = client

    def analyze(self, request: AnalysisRequest) -> AnalysisResult:
        if not self.settings.api_key:
            raise ConfigurationError(
                "Analyse indisponible : configurez OPENAI_API_KEY dans votre environnement local."
            )
        question = request.question.strip()
        if not question:
            raise AnalysisError("Saisissez une question avant de lancer l’analyse.")
        data_url = _image_data_url(request.frame.png, self.settings.image_max_edge)
        sources = tuple(request.web_sources[:MAX_WEB_SOURCES])
        context = format_web_context(sources)
        messages = conversation_messages(request.history)
        if context:
            messages.append(
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": context}],
                }
            )
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": question},
                    {"type": "input_image", "image_url": data_url, "detail": "high"},
                ],
            }
        )
        if self._client is None:
            self._client = OpenAI(
                api_key=self.settings.api_key,
                timeout=self.settings.api_timeout_seconds,
                max_retries=0,
            )
        start = time.monotonic()
        logger.info("analysis_started capture_id=%s", request.frame.capture_id)
        try:
            response = self._client.responses.create(
                model=self.settings.ai_model,
                instructions=SYSTEM_PROMPT,
                input=messages,
                max_output_tokens=1200,
                store=False,
                timeout=self.settings.api_timeout_seconds,
            )
        except AuthenticationError:
            self._failure("authentication")
            raise AnalysisError(
                "Le fournisseur a refusé l’authentification ; vérifiez votre clé API."
            ) from None
        except RateLimitError:
            self._failure("rate_limit")
            raise AnalysisError(
                "Limite API ou quota atteint ; vérifiez votre compte avant de réessayer."
            ) from None
        except APITimeoutError:
            self._failure("timeout")
            raise AnalysisError(
                "Le délai maximal d’analyse est dépassé. Vous pouvez réessayer manuellement."
            ) from None
        except APIConnectionError:
            self._failure("connection")
            raise AnalysisError(
                "Le fournisseur est inaccessible ; vérifiez votre connexion."
            ) from None
        except APIError:
            self._failure("api_error")
            raise AnalysisError(
                "Le fournisseur n’a pas pu traiter l’analyse. Vérifiez le modèle ou réessayez plus tard."
            ) from None
        text = getattr(response, "output_text", "")
        if not isinstance(text, str) or not text.strip():
            self._failure("empty_response")
            raise AnalysisError("Le fournisseur n’a retourné aucun texte exploitable.")
        elapsed = time.monotonic() - start
        logger.info(
            "analysis_completed capture_id=%s duration_seconds=%.3f",
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
        logger.warning("analysis_failed category=%s", category)
