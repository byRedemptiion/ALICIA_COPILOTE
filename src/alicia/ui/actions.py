"""Route explicit user requests without capturing the desktop for local actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event

from PySide6.QtCore import QObject

from alicia.actions.executor import ActionError, ActionExecutor
from alicia.actions.planner import ActionPlanningError, LocalActionPlanner
from alicia.actions.research import LocalSearchAnswerer


@dataclass(slots=True)
class _Request:
    text: str
    vocal: bool
    generation: int
    cancelled: Event = field(default_factory=Event)


class RequestController(QObject):
    """Compute plans first; commit effects only for a still-current user request.

    Workers observe only the thread-safe event. Qt/session state is checked on
    the GUI thread before each next stage, never read by a desktop worker.
    """

    def __init__(self, window, *, demo=False):
        super().__init__(window)
        self.window = window
        self.demo = demo
        self.planner = LocalActionPlanner(window.settings)
        self.executor = ActionExecutor(
            search_provider=window.research_provider,
            notes_directory=window.settings.notes_directory,
            answerer=(
                LocalSearchAnswerer(window.settings)
                if window.settings.ai_provider == "ollama"
                else None
            ),
        )
        self.request: _Request | None = None
        self.pending = None

    @property
    def busy(self):
        return self.request is not None

    def cancel(self):
        if self.request is not None:
            self.request.cancelled.set()
        self.request = None
        self.pending = None

    def submit(self, text: str, *, vocal=False):
        window = self.window
        text = text.strip()
        if not text or window.jobs or window.close_pending:
            return False
        self.cancel()
        request = self.request = _Request(text, vocal, window.session.generation)
        history = window.session.memory.snapshot()
        window.playback.stop()
        window.audio_generation += 1
        window.response_text = ""
        window.session.result = None
        window.answer.clear()
        window.sources.clear()
        window.sources.hide()
        window.conversation.phase = "routing"
        window.conversation.pause()
        window._state("Je prépare votre demande…", "thinking")
        window._event("Demande reçue : choix du traitement local.")
        self._job(
            "action_plan",
            request,
            lambda: self.planner.plan(request.text, history=history),
            "plan",
        )
        return True

    def _current(self, request):
        return (
            self.request is request
            and not request.cancelled.is_set()
            and request.generation == self.window.session.generation
            and not self.window.close_pending
        )

    def _job(self, kind, request, operation, stage):
        self.window._job(
            kind,
            operation,
            lambda result: self._received(request, stage, result),
            safe_errors=(ActionPlanningError, ActionError),
            on_error=lambda message: self._failed(request, message),
        )

    def _received(self, request, stage, result):
        if self._current(request):
            # Starting the next stage after finished avoids overlapping worker
            # lifecycle callbacks, including instant cached/planner responses.
            self.pending = (request, stage, result)

    def job_finished(self):
        if self.window.jobs or self.pending is None:
            return
        request, stage, result = self.pending
        self.pending = None
        if not self._current(request):
            return
        if stage == "plan":
            self._planned(request, result)
        elif stage == "prepared":
            self.window._state("J’exécute votre demande…", "thinking")
            self._job(
                "action_execute",
                request,
                lambda: self.executor.execute(result, cancelled=request.cancelled.is_set),
                "executed",
            )
        else:
            self._complete(request, result.text, result.sources, created_path=result.created_path)

    def _planned(self, request, plan):
        if plan.kind == "answer":
            self.request = None
            if not self.window.session.active or not self.window.consent.isChecked():
                self._display(
                    "Pour une question sur l’écran, lancez l’observation avec Reprendre "
                    "et autorisez l’analyse locale. Les consignes comme « ouvre la calculatrice » "
                    "restent disponibles sans observation."
                )
                return
            self.window.conversation.begin_answer(request.text, vocal=request.vocal)
        elif plan.kind == "clarify":
            self._complete(request, plan.message)
        elif self.demo:
            self._complete(
                request,
                "Les ouvertures et créations de fichiers sont désactivées dans la démonstration. "
                "Lancez Alicia normalement pour exécuter cette consigne.",
            )
        else:
            self.window._state(
                "Je recherche des informations…"
                if plan.kind == "search_web"
                else "Je prépare l’action…",
                "thinking",
            )
            if plan.kind == "search_web":
                self.window._event(
                    "Recherche explicitement demandée : la requête seule est envoyée au moteur."
                )
            self._job(
                "action_prepare",
                request,
                lambda: self.executor.prepare(plan, cancelled=request.cancelled.is_set),
                "prepared",
            )

    def _complete(self, request, text, sources=(), *, created_path=None):
        if not self._current(request):
            return
        self.request = None
        self.window.session.memory.append(request.text, text)
        self._display(text, sources, vocal=request.vocal, created_path=created_path)

    def _display(self, text, sources=(), *, vocal=False, created_path=None):
        window = self.window
        window.response_text = text
        window.answer.setPlainText(
            text + (f"\n\nFichier créé : {created_path}" if created_path is not None else "")
        )
        window.show_sources(sources)
        window.reveal_response()
        window._state("Votre demande est terminée")
        window._event("Résultat de la demande affiché.")
        window._update_controls()
        if vocal and window.session.active and window.conversation.auto_voice.isChecked():
            window.conversation.phase = "speaking"
            window.speak()
        else:
            window.conversation._finish_question()

    def _failed(self, request, message):
        if self._current(request):
            self.cancel()
            self.window._error(message)
