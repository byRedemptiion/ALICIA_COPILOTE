"""Prepare read-only work, then commit only explicitly requested local actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from alicia.actions.desktop import DesktopActions, DesktopError, app_identifier
from alicia.actions.models import (
    ActionPlan,
    ActionPlanError,
    parse_action_plan,
    validate_public_url,
)
from alicia.actions.notes import NoteError, NoteStore
from alicia.actions.research import ActionResearchError
from alicia.core.models import WebSource
from alicia.research.search import DuckDuckGoSearch, SearchError


class ActionError(RuntimeError):
    """Safe action failure suitable for the request panel."""


class ActionCancelled(ActionError):
    """No additional side effect is allowed for this cancelled request."""


@dataclass(frozen=True)
class PreparedAction:
    plan: ActionPlan
    sources: tuple[WebSource, ...] = ()
    search_fallback: bool = False
    answer: str = ""
    answer_unavailable: bool = False


@dataclass(frozen=True)
class ActionResult:
    text: str
    opened_url: str | None = None
    created_path: Path | None = None
    sources: tuple[WebSource, ...] = ()


def _check(cancelled) -> None:
    if cancelled():
        raise ActionCancelled("Demande annulée ; aucune nouvelle action n’est lancée.")


def _validated(plan: ActionPlan) -> ActionPlan:
    if not isinstance(plan, ActionPlan):
        raise ActionError("Cette action n’est pas prise en charge.")
    try:
        return parse_action_plan(plan.as_dict())
    except ActionPlanError:
        raise ActionError("Les paramètres de cette action ne sont pas valides.") from None


def _sources(sources) -> tuple[WebSource, ...]:
    valid = []
    for source in tuple(sources)[:5]:
        if not isinstance(source, WebSource):
            continue
        try:
            url = validate_public_url(source.url)
        except ActionPlanError:
            continue
        if (
            not isinstance(source.title, str)
            or not isinstance(source.snippet, str)
            or not isinstance(source.retrieved_at, datetime)
        ):
            continue
        valid.append(WebSource(source.title[:200], url, source.snippet[:900], source.retrieved_at))
    return tuple(valid)


def search_report(query: str, sources: tuple[WebSource, ...], answer: str = "") -> str:
    items = []
    for index, source in enumerate(sources, 1):
        title, snippet = escape(source.title), escape(source.snippet)
        url = escape(validate_public_url(source.url), quote=True)
        date = escape(source.retrieved_at.astimezone().strftime("%d/%m/%Y à %H:%M"))
        items.append(
            f'<article><h2><a href="{url}" target="_blank" rel="noreferrer noopener">[{index}] {title}</a></h2><p>{snippet}</p><small>Extrait récupéré le {date}. Date de publication non vérifiée.</small></article>'
        )
    answer_section = (
        f'<section><h2>Réponse d’Alicia</h2><p style="white-space:pre-wrap">{escape(answer)}</p><p><small>Synthèse IA fondée sur les extraits ci-dessous. Vérifiez les sources ; les pages complètes n’ont pas été consultées.</small></p></section>'
        if answer
        else "<p>La synthèse de la réponse n’est pas disponible. Voici les résultats du moteur et leurs sources.</p>"
    )
    return (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">"
        "<title>Recherche Alicia</title><style>body{font:18px system-ui;max-width:920px;margin:3rem auto;padding:0 1rem;background:#0d1622;color:#e9edf5}a{color:#a2ead9}article{padding:1.2rem;margin:1rem 0;background:#1a2838;border-radius:16px}h2{font-size:1.2rem}small{color:#afbdcf}</style></head><body>"
        f"<h1>{escape(query)}</h1>{answer_section}<h2>Sources et extraits</h2><p>Les textes ci-dessous sont les extraits du moteur ; les pages complètes n’ont pas été consultées. Consultez les sources pour vérifier leur application à votre situation.</p>{''.join(items)}</body></html>"
    )


class ActionExecutor:
    def __init__(
        self,
        *,
        search_provider=None,
        desktop=None,
        notes=None,
        notes_directory: Path | None = None,
        answerer=None,
    ):
        self.search_provider = search_provider or DuckDuckGoSearch()
        self.desktop = desktop or DesktopActions()
        self.notes = notes or NoteStore(notes_directory)
        self.answerer = answerer

    def prepare(self, plan: ActionPlan, *, cancelled=lambda: False) -> PreparedAction:
        _check(cancelled)
        plan = _validated(plan)
        if plan.kind == "open_app":
            try:
                app_identifier(plan.app)
            except DesktopError as error:
                raise ActionError(str(error)) from None
        if plan.kind != "search_web":
            return PreparedAction(plan)
        try:
            sources = _sources(self.search_provider.search(plan.query))
        except SearchError:
            _check(cancelled)
            return PreparedAction(plan, search_fallback=True)
        _check(cancelled)
        if not sources:
            return PreparedAction(plan, search_fallback=True)
        answer = ""
        if self.answerer is not None:
            try:
                answer = self.answerer.summarize(plan.query, sources, cancelled=cancelled)
            except ActionResearchError:
                pass
        _check(cancelled)
        if not isinstance(answer, str) or not answer.strip() or len(answer) > 12000:
            answer = ""
        return PreparedAction(plan, sources, answer=answer, answer_unavailable=not bool(answer))

    def execute(self, prepared: PreparedAction, *, cancelled=lambda: False) -> ActionResult:
        _check(cancelled)
        if not isinstance(prepared, PreparedAction):
            raise ActionError("L’action doit être préparée avant son exécution.")
        plan = _validated(prepared.plan)
        try:
            if plan.kind == "open_url":
                opened = self.desktop.open_url(plan.url, cancelled=cancelled)
                if not opened:
                    _check(cancelled)
                    raise ActionError("Le navigateur n’a pas été ouvert.")
                return ActionResult(
                    "J’ai demandé l’ouverture de cette page dans votre navigateur.",
                    opened_url=plan.url,
                )
            if plan.kind == "open_app":
                _check(cancelled)
                name = self.desktop.open_app(plan.app, cancelled=cancelled)
                _check(cancelled)
                return ActionResult(f"J’ai demandé l’ouverture de {name}.")
            if plan.kind == "open_folder":
                _check(cancelled)
                self.desktop.open_folder(plan.folder, cancelled=cancelled)
                _check(cancelled)
                return ActionResult("J’ai demandé l’ouverture de ce dossier dans l’Explorateur.")
            if plan.kind == "create_note":
                path = self.notes.create_note(plan.title, plan.content, cancelled=cancelled)
                if path is None:
                    _check(cancelled)
                    raise ActionError("La note n’a pas été créée.")
                return ActionResult(
                    "Votre note est enregistrée dans les notes d’Alicia.", created_path=path
                )
            if plan.kind == "search_web":
                sources = _sources(prepared.sources)
                if prepared.search_fallback or not sources:
                    url = "https://duckduckgo.com/?" + urlencode({"q": plan.query})
                    _check(cancelled)
                    if not self.desktop.open_url(url, cancelled=cancelled):
                        _check(cancelled)
                        raise ActionError("Le navigateur n’a pas été ouvert.")
                    return ActionResult(
                        "Le moteur ne m’a pas fourni de sources vérifiables. J’ai ouvert la recherche dans votre navigateur.",
                        opened_url=url,
                    )
                answer = (
                    prepared.answer
                    if isinstance(prepared.answer, str) and len(prepared.answer) <= 12000
                    else ""
                )
                content = search_report(plan.query, sources, answer)
                _check(cancelled)
                path = self.notes.create_report(content, cancelled=cancelled)
                if path is None:
                    _check(cancelled)
                    raise ActionError("La page de résultats n’a pas été créée.")
                _check(cancelled)
                if not self.desktop.open_report(path, path.parent, cancelled=cancelled):
                    _check(cancelled)
                    raise ActionError("La page de résultats n’a pas été ouverte.")
                message = (
                    answer + "\n\nJ’ai ouvert une page avec cette réponse et ses sources."
                    if answer
                    else "La synthèse n’est pas disponible. J’ai ouvert les résultats du moteur et leurs sources."
                )
                return ActionResult(
                    message + " Les pages complètes n’ont pas été consultées.",
                    opened_url=path.resolve().as_uri(),
                    created_path=path,
                    sources=sources,
                )
        except (DesktopError, NoteError, ActionPlanError) as error:
            raise ActionError(str(error)) from None
        raise ActionError("Cette demande ne nécessite aucune action de bureau.")
