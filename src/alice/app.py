"""Composition : crée les services à partir de la configuration (sans Qt)."""

from __future__ import annotations

import logging
import platform
import sys
from dataclasses import dataclass

from alice import __version__
from alice.core.ai.base import VisionModel
from alice.core.ai.factory import create_model
from alice.core.analysis.service import AnalysisService
from alice.core.capture.service import CaptureService
from alice.core.config import Settings
from alice.core.session.context import SessionContext

log = logging.getLogger("alice.app")


@dataclass
class Services:
    settings: Settings
    capture: CaptureService
    model: VisionModel
    session: SessionContext
    analysis: AnalysisService
    demo: bool


def build_services(
    settings: Settings, *, demo: bool = False, model: VisionModel | None = None
) -> Services:
    capture = (
        CaptureService.demo(settings.capture.keep_last_frames)
        if demo
        else CaptureService.for_windows(settings.capture)
    )
    model = model or create_model(settings.ai)
    session = SessionContext(settings.ai.history_turns)
    analysis = AnalysisService(settings, capture, model, session)
    return Services(settings, capture, model, session, analysis, demo)


def log_startup(settings: Settings, log_file: str) -> None:
    log.info(
        "Démarrage d'Alice %s — Python %s, %s %s",
        __version__,
        platform.python_version(),
        platform.system(),
        platform.version(),
    )
    log.info("Logs : %s — configuration : %s", log_file, ", ".join(settings.sources))
    model = (
        settings.ai.gemini.model if settings.ai.provider == "gemini" else settings.ai.ollama.model
    )
    log.info(
        "IA : %s/%s — clé Gemini %s — capture : %s (repli écran %s)",
        settings.ai.provider,
        model if settings.ai.provider != "fake" else "fake",
        "présente" if settings.ai.gemini.api_key else "absente",
        settings.capture.backend,
        "oui" if settings.capture.monitor_fallback else "non",
    )
    if sys.platform == "win32":
        try:
            import windows_capture  # noqa: F401

            log.debug("Module windows-capture chargé")
        except ImportError as exc:
            log.error("Module windows-capture indisponible : %r", exc)
