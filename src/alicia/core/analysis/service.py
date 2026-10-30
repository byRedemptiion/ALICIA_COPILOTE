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
from alicia.core.errors import AliciaError, CaptureError, ProviderError, ProviderErrorKind
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
        self.game_profile = settings.game_profile  # « auto » ou un profil choisi dans l'interface
        self.vision_mode = settings.capture.mode  # window | cursor | screen (modifiable en direct)
        self.timeline = None  # Timeline (mémoire de partie), branchée par l'interface
        self.settings = settings
        self.capture = capture
        self.model = model
        self.session = session

    def analyze(
        self,
        window: WindowInfo | None,
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
                if local_transcript:
                    from alicia.core.audio.wake import strip_wake_word

                    heard = local_transcript
                    local_transcript = strip_wake_word(local_transcript)
                    if not local_transcript:
                        raise AliciaError(
                            "Oui ? Dis ta demande juste après « Alicia ».",
                            detail=f"seulement le mot de réveil : {heard!r}",
                        )
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
            vision = self.vision_mode
            if window is None and frame is None and vision == "window":
                vision = "screen"  # pas de jeu (bureau, réglages…) : l'écran entier
                log.info("Aucune application au premier plan : je regarde l'écran entier")
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
                window.title if window is not None else "—",
            )
            if audio is None:
                log.debug("Question : %s", question)
            if frame is None:
                try:
                    frame = self.capture.capture(window, vision, self.settings.capture.cursor_box)
                except CaptureError as exc:
                    if vision != "window":
                        raise
                    # Fenêtre réduite ou impossible à capturer : l'écran entier à la place.
                    log.warning(
                        "Capture de l'application impossible, écran entier : %s", exc.detail
                    )
                    frame = self.capture.capture(window, "screen", self.settings.capture.cursor_box)
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
            profile = resolve_profile(frame.window, self.game_profile)
            past_images, past_note = self._past_images(question if audio is None else "")
            request = AnalysisRequest(
                question=question,
                images=(image, *past_images),
                system_prompt=build_system_prompt(
                    profile.prompt_context(web_search) + vision_note(frame) + past_note,
                    spoken=spoken,
                ),
                history=self.session.history(),
                max_output_tokens=self.settings.ai.max_output_tokens,
                temperature=self.settings.ai.temperature,
                audio=audio,
                web_search=web_search,
            )
            log.info(
                "Jeu : %s (fenêtre %s, %s)%s",
                profile.name,
                frame.window.exe_name or "?",
                "choisi" if self.game_profile != "auto" else "détecté",
                f" — sources prioritaires : {', '.join(profile.sources)}"
                if web_search and profile.sources
                else "",
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

    def _past_images(self, question: str) -> tuple[tuple, str]:  # type: ignore[type-arg]
        """Question sur le passé (« il y a une heure ») : images de ce moment, si gardées."""
        if self.timeline is None or not question:
            return (), ""
        from datetime import datetime

        from PIL import Image

        from alicia.core.capture.timeline import find_past_moment

        when = find_past_moment(question)
        if when is None:
            return (), ""
        found = self.timeline.near(when, count=3)
        label = when.astimezone().strftime("%H:%M")
        if not found:
            log.info("Mémoire de partie : aucune image vers %s", label)
            return (), (
                f"\n\nLe joueur parle d'un moment passé (vers {label}), mais aucune capture de "
                "ce moment n'est gardée : dis-le simplement."
            )
        images, times = [], []
        for moment, path in found:
            try:
                with Image.open(path) as picture:
                    images.append(
                        prepare_image(
                            picture.convert("RGB"),
                            self.settings.capture.max_image_side,
                            self.settings.capture.jpeg_quality,
                        )
                    )
                times.append(moment.astimezone().strftime("%H:%M:%S"))
            except OSError as exc:
                log.warning("Mémoire de partie : image illisible %s (%r)", path.name, exc)
        if not images:
            return (), ""
        now = datetime.now().astimezone().strftime("%H:%M")
        log.info(
            "Mémoire de partie : %d image(s) vers %s jointes à la question", len(images), label
        )
        return tuple(images), (
            f"\n\nLa 1re image est l'écran actuel ({now}). Les suivantes viennent de la mémoire "
            f"de partie, prises à {', '.join(times)}, parce que le joueur parle de ce moment "
            "passé : appuie-toi sur elles pour répondre."
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


def vision_note(frame: Frame) -> str:
    """Précise à l'IA ce qu'elle regarde (écran entier, zone du curseur)."""
    if frame.mode == "cursor":
        return (
            "\n\nL'image est une zone autour du curseur de la souris du joueur. Le cercle rose "
            "marque le curseur : c'est ce qu'il te montre (objet, sort, bouton, texte) ; "
            "réponds d'abord à propos de cet élément."
        )
    if frame.mode == "screen":
        note = "\n\nL'image montre l'écran entier du joueur, pas seulement le jeu."
        if frame.cursor is not None:
            note += " Le cercle rose marque son curseur de souris."
        return note
    return ""
