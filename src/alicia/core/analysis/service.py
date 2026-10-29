"""AnalysisService : capture + contexte + question → IA → résultat, entièrement journalisé."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from alicia.core.actions.controller import ActionReply
from alicia.core.ai.base import (
    AnalysisRequest,
    AnalysisResult,
    DeltaCallback,
    PreparedAudio,
    VisionModel,
)
from alicia.core.ai.image_prep import prepare_image
from alicia.core.ai.prompts import VOICE_QUESTION, TranscriptSplitter, build_system_prompt
from alicia.core.capture.models import Frame, WindowInfo
from alicia.core.capture.service import CaptureService
from alicia.core.config import Settings
from alicia.core.errors import AliciaError, ProviderError, ProviderErrorKind
from alicia.core.logging_setup import operation
from alicia.core.session.context import SessionContext
from alicia.games.profiles import resolve_profile

log = logging.getLogger("alicia.analysis")


@dataclass
class AnalysisOutcome:
    operation_id: str
    frame: Frame | None
    result: AnalysisResult | None
    profile: str
    total_ms: int
    transcript: str | None = None  # question orale transcrite
    action: ActionReply | None = None  # demande d'action sur le PC (pas d'appel IA)


class AnalysisService:
    def __init__(
        self,
        settings: Settings,
        capture: CaptureService,
        model: VisionModel,
        session: SessionContext,
        transcriber=None,  # type: ignore[no-untyped-def]  # LocalTranscriber (voix → texte), facultatif
        router=None,  # type: ignore[no-untyped-def]  # texte → ActionReply | None (actions sur le PC)
    ) -> None:
        self.router = router
        self.transcriber = transcriber
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
        on_transcript=None,  # type: ignore[no-untyped-def]  # question orale transcrite
        cancel: threading.Event | None = None,
        audio: PreparedAudio | None = None,
        web_search: bool = False,
        spoken: bool = False,
    ) -> AnalysisOutcome:
        with operation() as op_id:
            started = time.perf_counter()
            local_transcript = None
            if audio is not None and self.transcriber is not None:
                local_transcript = self.transcriber.transcribe(audio)
                if not local_transcript:
                    raise AliciaError(
                        "Je n'ai rien compris : parle un peu plus fort ou plus près du micro, "
                        "puis réessaie.",
                        detail="transcription vide",
                    )
                if on_transcript is not None:
                    on_transcript(local_transcript)
                log.debug("Transcription : %s", local_transcript)
                question, audio = local_transcript, None
            if audio is not None:
                question = VOICE_QUESTION
            else:
                question = question.strip() or "Que vois-tu d'important sur cet écran ?"
                if self.router is not None:
                    reply = self.router(question)
                    if reply is not None:
                        total = int((time.perf_counter() - started) * 1000)
                        log.info("Demande traitée comme action « %s » (sans IA)", reply.intent)
                        return AnalysisOutcome(
                            op_id, None, None, "", total, local_transcript, action=reply
                        )
            mode = (
                f"question orale {audio.duration_s:.1f} s"
                if audio
                else (
                    "question orale transcrite localement"
                    if local_transcript
                    else "question écrite"
                )
            )
            log.info(
                "Analyse demandée (%s%s) — fenêtre « %s »",
                mode,
                ", recherche web autorisée" if web_search else "",
                window.title,
            )
            if audio is None:
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
                system_prompt=build_system_prompt(profile.context, spoken=spoken),
                history=self.session.history(),
                max_output_tokens=self.settings.ai.max_output_tokens,
                temperature=self.settings.ai.temperature,
                audio=audio,
                web_search=web_search,
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
            splitter = None
            sink = on_delta
            if audio is not None:
                splitter = TranscriptSplitter(
                    on_transcript or (lambda _t: None), on_delta or (lambda _t: None)
                )
                sink = splitter.feed
            try:
                result = self.model.analyze(request, on_delta=sink, cancel=cancel)
            except ProviderError as exc:
                level = logging.INFO if exc.kind is ProviderErrorKind.CANCELLED else logging.ERROR
                log.log(level, "Appel IA échoué [%s] : %s", exc.kind, exc.detail)
                raise
            transcript = None
            if splitter is not None:
                splitter.close()
                transcript = splitter.transcript
                from alicia.core.ai.prompts import split_transcript

                _, result.text = split_transcript(result.text)
                log.info("Question orale transcrite : %d caractères", len(transcript or ""))
                log.debug("Transcription : %s", transcript)
                question = transcript or "(question orale inaudible)"
            self.session.record(question, result.text)
            if result.sources:
                log.info(
                    "Recherche web : %d source(s), requêtes %s",
                    len(result.sources),
                    result.search_queries,
                )
            if "search_disabled" in result.extra:
                log.warning("Réponse produite sans recherche web (refusée par le fournisseur)")
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
            return AnalysisOutcome(
                op_id, frame, result, profile.key, total, transcript or local_transcript
            )

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
