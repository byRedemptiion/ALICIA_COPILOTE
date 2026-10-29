"""Point d'entrée : ``alicia`` (ou ``python -m alicia``)."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from alicia import __version__
from alicia.core.config import load_settings
from alicia.core.errors import AliciaError

log = logging.getLogger("alicia.app")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="alicia", description="Alicia, copilote IA pour jeux vidéo"
    )
    parser.add_argument("--version", action="version", version=f"Alicia {__version__}")
    parser.add_argument("--debug", action="store_true", help="logs détaillés")
    parser.add_argument("--demo", action="store_true", help="capture synthétique, sans jeu")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="parcours complet hors écran (démo + IA factice), puis sortie",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ["ALICE_AI_PROVIDER"] = "fake"
    if args.debug:
        os.environ["ALICE_LOG_LEVEL"] = "DEBUG"

    from alicia.core.capture.win32 import enable_dpi_awareness
    from alicia.core.config import migrate_legacy_dirs
    from alicia.core.logging_setup import setup_logging

    moved = migrate_legacy_dirs()
    try:
        settings = load_settings()
    except AliciaError as exc:
        print(f"Configuration invalide : {exc.user_message}", file=sys.stderr)
        return 2
    log_file = setup_logging(settings.log_dir, settings.log_level)
    for line in moved:
        log.info("Dossier renommé (Alice → Alicia) : %s", line)
    enable_dpi_awareness()

    from PySide6.QtWidgets import QApplication

    from alicia.app import build_services, log_startup
    from alicia.ui.main_window import MainWindow

    log_startup(settings, str(log_file))
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Alicia")
    try:
        services = build_services(settings, demo=args.demo or args.smoke_test)
    except AliciaError as exc:
        log.critical("Démarrage impossible : %s", exc.detail)
        print(exc.user_message, file=sys.stderr)
        return 1
    window = MainWindow(services, str(log_file))

    if args.smoke_test:
        return _smoke(app, window)

    window.show()
    code = app.exec()
    log.info("Arrêt d'Alicia (code %d)", code)
    return code


def _smoke(app, window) -> int:  # type: ignore[no-untyped-def]
    """Sélection → Démarrer → Analyser → réponse, sans écran ni réseau."""
    from PySide6.QtCore import QTimer

    outcome: dict[str, object] = {}

    def done(value: object) -> None:
        outcome["value"] = value
        app.quit()

    window.analysis_done.connect(done)
    window.window_list.setCurrentRow(0)
    window.question.setText("Quel objet semble le plus intéressant sur cet écran ?")
    QTimer.singleShot(0, window.analyze_or_cancel)
    QTimer.singleShot(15000, app.quit)
    app.exec()
    value = outcome.get("value")
    answer = window.answer.toPlainText()
    if value is None or isinstance(value, Exception) or "Image reçue" not in answer:
        print(f"SMOKE TEST ÉCHOUÉ : {value!r} / {answer!r}", file=sys.stderr)
        return 1
    print("Smoke test OK :", answer)
    window.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
