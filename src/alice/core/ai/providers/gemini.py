"""Google Gemini (API REST, réponse en streaming SSE). Aucun SDK requis."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from typing import Any

import httpx

from alice.core.ai.base import AnalysisRequest
from alice.core.ai.providers.http_base import Chunk, HttpVisionModel, error_message, json_lines
from alice.core.config import GeminiSettings
from alice.core.errors import ProviderError, ProviderErrorKind

KEY_HELP = (
    "Crée une clé gratuite sur https://aistudio.google.com (« Get API key »), "
    "puis colle-la dans le fichier .env : GEMINI_API_KEY=ta_clé"
)


class GeminiModel(HttpVisionModel):
    provider = "gemini"

    def __init__(
        self, settings: GeminiSettings, timeout_s: float, client: httpx.Client | None = None
    ) -> None:
        super().__init__(timeout_s, client)
        self.settings = settings
        self.model = settings.model

    @property
    def label(self) -> str:
        return "Gemini"

    def check(self) -> str | None:
        if not self.settings.api_key:
            return "Clé Gemini manquante. " + KEY_HELP
        if not self.model:
            return "Aucun modèle Gemini configuré (section [ai.gemini] model)."
        return None

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.settings.api_key.get()}

    def _request(self, request: AnalysisRequest) -> tuple[str, dict[str, str], dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        for turn in request.history:
            contents.append({"role": "user", "parts": [{"text": turn.question}]})
            contents.append({"role": "model", "parts": [{"text": turn.answer}]})
        parts: list[dict[str, Any]] = [
            {
                "inline_data": {
                    "mime_type": image.mime_type,
                    "data": base64.b64encode(image.data).decode(),
                }
            }
            for image in request.images
        ]
        parts.append({"text": request.question})
        contents.append({"role": "user", "parts": parts})

        generation: dict[str, Any] = {
            "maxOutputTokens": request.max_output_tokens,
            "temperature": request.temperature,
        }
        thinking: dict[str, Any] = {}
        if self.settings.thinking_budget is not None:
            thinking["thinkingBudget"] = self.settings.thinking_budget
        if self.settings.thinking_level:
            thinking["thinkingLevel"] = self.settings.thinking_level
        if thinking:
            generation["thinkingConfig"] = thinking

        body = {
            "systemInstruction": {"parts": [{"text": request.system_prompt}]},
            "contents": contents,
            "generationConfig": generation,
        }
        url = f"{self.settings.base_url}/models/{self.model}:streamGenerateContent?alt=sse"
        return url, self._headers(), body

    def _parse_lines(self, lines: Iterator[str]) -> Iterator[Chunk]:
        for event in json_lines(lines, prefix="data:"):
            feedback = event.get("promptFeedback") or {}
            if feedback.get("blockReason"):
                raise ProviderError(
                    ProviderErrorKind.BAD_REQUEST,
                    "Gemini a refusé la demande (filtre de contenu).",
                    detail=f"blockReason={feedback['blockReason']}",
                )
            usage = event.get("usageMetadata") or {}
            text_parts: list[str] = []
            finish = None
            for candidate in event.get("candidates") or []:
                finish = candidate.get("finishReason") or finish
                for part in (candidate.get("content") or {}).get("parts") or []:
                    if part.get("thought"):
                        continue  # résumé de réflexion interne : pas pour le joueur
                    if isinstance(part.get("text"), str):
                        text_parts.append(part["text"])
            yield Chunk(
                text="".join(text_parts),
                input_tokens=usage.get("promptTokenCount"),
                output_tokens=usage.get("candidatesTokenCount"),
                finish_reason=finish,
            )

    def _http_error(self, status: int, body: str) -> ProviderError:
        message = error_message(body)
        lowered = message.lower()
        if status in (401, 403) or "api key" in lowered or "api_key" in lowered:
            return ProviderError(
                ProviderErrorKind.AUTH,
                "Clé Gemini refusée. " + KEY_HELP,
                detail=f"HTTP {status}: {message}",
                status_code=status,
            )
        if status == 429:
            return ProviderError(
                ProviderErrorKind.RATE_LIMIT,
                "Quota Gemini atteint (offre gratuite limitée par minute et par jour). "
                "Réessaie dans une minute.",
                detail=f"HTTP 429: {message}",
                status_code=status,
            )
        if status == 404:
            return ProviderError(
                ProviderErrorKind.BAD_REQUEST,
                f"Modèle Gemini « {self.model} » introuvable. Liste les modèles disponibles "
                "avec : alice-diag models",
                detail=f"HTTP 404: {message}",
                status_code=status,
            )
        if status >= 500:
            return ProviderError(
                ProviderErrorKind.UNAVAILABLE,
                "Gemini est momentanément indisponible.",
                detail=f"HTTP {status}: {message}",
                status_code=status,
            )
        return ProviderError(
            ProviderErrorKind.BAD_REQUEST,
            f"Requête refusée par Gemini : {message}",
            detail=f"HTTP {status}: {message}",
            status_code=status,
        )

    def _empty_answer(self, finish_reason: str | None) -> ProviderError:
        if finish_reason == "MAX_TOKENS":
            hint = " Augmente [ai] max_output_tokens ou réduis la réflexion (thinking_budget)."
        elif finish_reason in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST"):
            hint = " La réponse a été bloquée par le filtre de contenu."
        else:
            hint = ""
        return ProviderError(
            ProviderErrorKind.BAD_REQUEST,
            "Gemini a renvoyé une réponse vide." + hint,
            detail=f"finishReason={finish_reason}",
        )

    def list_models(self) -> list[str]:
        """Modèles utilisables avec ``generateContent`` pour cette clé."""
        problem = self.check()
        if problem:
            raise ProviderError(ProviderErrorKind.AUTH, problem)
        try:
            response = self._client.get(
                f"{self.settings.base_url}/models",
                params={"pageSize": 1000},
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise ProviderError(
                ProviderErrorKind.UNAVAILABLE, "Impossible de joindre Gemini.", detail=repr(exc)
            ) from exc
        if response.status_code >= 400:
            raise self._http_error(response.status_code, response.text[:2000])
        names = []
        for item in response.json().get("models", []):
            if "generateContent" in item.get("supportedGenerationMethods", []):
                names.append(str(item.get("name", "")).removeprefix("models/"))
        return sorted(names)
