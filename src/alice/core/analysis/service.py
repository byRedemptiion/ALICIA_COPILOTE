"""AnalysisService : capture + contexte + question → IA → résultat, entièrement journalisé."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from alice.core.ai.base import AnalysisRequest, AnalysisResult, DeltaCallback, VisionModel
from alice.core.ai.image_prep import prepare_image
from alice.core.ai.prompts import build_system_prompt
from alice.core.capture.models import Frame, WindowInfo
from alice.core.capture.service import CaptureService
from alice.core.config import Settings
from alice.core.errors import ProviderError, ProviderErrorKind
from alice.core.logging_setup import operation
from alice.core.session.context import SessionContext
from alice.games.profiles import resolve_profile

log = logging.getLogger("alice.analysis")


@dataclass
class AnalysisOutcome:
    operation_id: str
    frame: Frame
    result: AnalysisResult
    profile: str
    total_ms: int


class AnalysisService:
    def __init__(
        self,
        settings: Settings,
        capture: CaptureService,
        model: VisionModel,
        session: SessionContext,
    ) -> None:
        self.settings = settings
        self.capture = capture
        self.model = model
        self.session = session

    def analyze(
        self,
        window: WindowInfo,
        question: str,
        *,
        frame: Frame | None = None,
        on_frame=None,  # type: ignore[no-untyped-def]  # appelé dès que la capture est prête
        on_delta: DeltaCallback | None = None,
        cancel: threading.Event | None = None,
    ) -> AnalysisOutcome:
        question = question.strip() or "Que vois-tu d'important sur cet écran ?"
        with operation() as op_id:
            started = time.perf_counter()
            log.info("Analyse demandée (envoi manuel) — fenêtre « %s »", window.title)
            log.debug("Question : %s", question)
            if frame is None:
                frame = self.capture.capture(window)
            if on_frame is not None:
                on_frame(frame)
            if cancel is not None and cancel.is_set():
                raise ProviderError(ProviderErrorKind.CANCELLED, "Analyse annulée.")
            self._maybe_save(frame, op_id)

            image = prepare_image(
                frame.image,
                self.settings.capture.max_image_side,
                self.settings.capture.jpeg_quality,
            )
            profile = resolve_profile(frame.window, self.settings.game_profile)
            request = AnalysisRequest(
                question=question,
                images=(image,),
                system_prompt=build_system_prompt(profile.context),
                history=self.session.history(),
                max_output_tokens=self.settings.ai.max_output_tokens,
                temperature=self.settings.ai.temperature,
            )
            log.info(
                "Appel IA %s/%s — image %dx%d, %d Ko, profil %s, historique %d",
                self.model.provider,
                self.model.model,
                image.width,
                image.height,
                len(image.data) // 1024,
                profile.key,
                len(request.history),
            )
            try:
                result = self.model.analyze(request, on_delta=on_delta, cancel=cancel)
            except ProviderError as exc:
                level = logging.INFO if exc.kind is ProviderErrorKind.CANCELLED else logging.ERROR
                log.log(level, "Appel IA échoué [%s] : %s", exc.kind, exc.detail)
                raise
            self.session.record(question, result.text)
            total = int((time.perf_counter() - started) * 1000)
            log.info(
                "Réponse IA : %d caractères, 1er mot %s ms, IA %d ms, total %d ms, jetons %s/%s, fin %s",
                len(result.text),
                result.first_token_ms,
                result.latency_ms,
                total,
                result.input_tokens,
                result.output_tokens,
                result.finish_reason,
            )
            log.debug("Réponse : %s", result.text)
            return AnalysisOutcome(op_id, frame, result, profile.key, total)

    def _maybe_save(self, frame: Frame, op_id: str) -> None:
        if not self.settings.capture.save_captures:
            return
        folder = self.settings.captures_dir
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{frame.captured_at:%Y%m%d-%H%M%S}-{op_id}-{frame.backend}.png"
            frame.image.save(path)
            log.info("Capture enregistrée : %s", path)
        except OSError as exc:
            log.warning("Capture non enregistrée : %s", exc)
