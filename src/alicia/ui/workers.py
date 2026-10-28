import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, Signal

logger = logging.getLogger(__name__)


class WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, operation: Callable, safe_errors: tuple[type[Exception], ...] = ()):
        super().__init__()
        self.operation = operation
        self.safe_errors = safe_errors
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            self.signals.succeeded.emit(self.operation())
        except Exception as error:
            logger.error("worker_failed error_type=%s", type(error).__name__)
            message = (
                str(error)
                if isinstance(error, self.safe_errors)
                else "Une erreur interne est survenue. Consultez les logs."
            )
            self.signals.failed.emit(message)
        finally:
            self.signals.finished.emit()
