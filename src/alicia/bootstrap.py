import logging
import sys

from PySide6.QtWidgets import QApplication

from alicia.capture.demo import DemoCapture
from alicia.capture.isolated import IsolatedWindowsCapture
from alicia.config import load_settings
from alicia.core.ports import ConfigurationError
from alicia.logging_config import configure_logging
from alicia.providers import create_vision_provider
from alicia.ui.main_window import MainWindow


def run(options) -> int:
    try:
        settings = load_settings()
        vision_provider = create_vision_provider(settings)
        log_path = configure_logging(settings.log_directory)
    except (ConfigurationError, OSError) as error:
        # Configuration errors contain variable names, never their values.
        message = (
            str(error)
            if isinstance(error, ConfigurationError)
            else "Répertoire de logs inaccessible."
        )
        print("Alicia : " + message, file=sys.stderr)
        return 2
    logger = logging.getLogger("alicia")
    logger.info(
        "application_started mode=%s", "demo" if options.demo or options.smoke_test else "windows"
    )
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Alicia")
    app.setOrganizationName("Alicia")
    source = DemoCapture() if options.demo or options.smoke_test else IsolatedWindowsCapture()
    window = MainWindow(settings, source, vision_provider, demo=isinstance(source, DemoCapture))
    window.show()
    window._event(f"Journal local : {log_path}")
    if options.smoke_test:
        from alicia.ui.smoke import run_smoke

        return run_smoke(app, window, options.screenshot)
    return app.exec()
