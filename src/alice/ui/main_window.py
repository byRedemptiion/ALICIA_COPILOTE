"""Fenêtre principale d'Alice (V0.1) : sobre, fonctionnelle, jamais bloquante."""

from __future__ import annotations

import logging
import threading
from typing import Any

from PIL import Image
from PySide6.QtCore import Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QImage, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from alice import __version__
from alice.app import Services
from alice.core.analysis.service import AnalysisOutcome
from alice.core.capture.models import Frame, WindowInfo
from alice.core.errors import AliceError, ProviderError, ProviderErrorKind
from alice.core.logging_setup import make_filter, make_formatter, set_level
from alice.ui.workers import LogBridge, QtLogHandler, Task

log = logging.getLogger("alice.ui")
MAX_LOG_LINES = 3000
DEFAULT_HOTKEY_QUESTION = (
    "Que vois-tu d'important sur mon écran, et quel est le meilleur choix à faire maintenant ?"
)


def pixmap_from_image(image: Image.Image) -> QPixmap:
    rgb = image.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    qimage = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimage.copy())


class PreviewLabel(QLabel):
    """Aperçu qui conserve les proportions quand la fenêtre change de taille."""

    def __init__(self) -> None:
        super().__init__("Aucune capture pour l'instant.")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("background:#111; color:#888; border-radius:6px;")
        self._pixmap: QPixmap | None = None

    def set_image(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self._refresh()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        if self._pixmap is not None:
            self.setPixmap(
                self._pixmap.scaled(
                    self.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )


class MainWindow(QMainWindow):
    analysis_done = Signal(object)  # AnalysisOutcome ou exception — utile aux tests

    def __init__(self, services: Services, log_file: str | None = None) -> None:
        super().__init__()
        self.services = services
        self.log_file = log_file
        self.pool = QThreadPool.globalInstance()
        self.windows: list[WindowInfo] = []
        self.observed: WindowInfo | None = None
        self.generation = 0
        self.busy = False
        self.cancel_event: threading.Event | None = None
        self._live_tasks: set[Task] = set()

        self.setWindowTitle(f"Alice {__version__}" + (" — DÉMO" if services.demo else ""))
        self.resize(1280, 820)
        self._build_ui()
        self._attach_logs()
        self.refresh_windows()
        self._update_state()
        self._setup_hotkey()

    # --- construction -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.status = QLabel()
        self.status.setStyleSheet("font-weight:600; padding:4px 0;")
        model = self.services.model
        self.provider_label = QLabel(f"IA : {model.provider} / {model.model}")
        self.provider_label.setStyleSheet("color:#777;")
        self.hotkey_label = QLabel("")
        self.hotkey_label.setStyleSheet("color:#4a9; padding-right:12px;")
        header = QHBoxLayout()
        header.addWidget(self.status, 1)
        header.addWidget(self.hotkey_label)
        header.addWidget(self.provider_label)

        # Fenêtres
        self.window_list = QListWidget()
        self.window_list.itemSelectionChanged.connect(self._update_state)
        self.window_list.itemDoubleClicked.connect(lambda _item: self.toggle_observation())
        self.refresh_button = QPushButton("Actualiser")
        self.refresh_button.clicked.connect(self.refresh_windows)
        self.start_button = QPushButton("Démarrer")
        self.start_button.clicked.connect(self.toggle_observation)
        self.capture_button = QPushButton("Capturer")
        self.capture_button.clicked.connect(self.capture_now)
        buttons = QHBoxLayout()
        for button in (self.refresh_button, self.start_button, self.capture_button):
            buttons.addWidget(button)
        windows_box = QGroupBox("Fenêtre du jeu")
        windows_layout = QVBoxLayout(windows_box)
        windows_layout.addWidget(self.window_list)
        windows_layout.addLayout(buttons)

        # Aperçu
        self.preview = PreviewLabel()
        self.preview_info = QLabel("")
        self.preview_info.setStyleSheet("color:#777;")
        self.preview_info.setWordWrap(True)
        preview_box = QGroupBox("Dernière capture")
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.addWidget(self.preview, 1)
        preview_layout.addWidget(self.preview_info)

        # Question / réponse
        self.question = QLineEdit()
        self.question.setPlaceholderText("Ex. : Quel objet est le meilleur pour mon héros ?")
        self.question.returnPressed.connect(self.analyze_or_cancel)
        self.analyze_button = QPushButton("Analyser")
        self.analyze_button.setDefault(True)
        self.analyze_button.clicked.connect(self.analyze_or_cancel)
        ask = QHBoxLayout()
        ask.addWidget(self.question, 1)
        ask.addWidget(self.analyze_button)
        self.answer = QTextBrowser()
        self.answer.setOpenExternalLinks(True)
        answer_font = QFont(self.answer.font())
        answer_font.setPointSizeF(answer_font.pointSizeF() + 2)
        self.answer.setFont(answer_font)
        self.answer_info = QLabel("")
        self.answer_info.setStyleSheet("color:#777;")
        answer_box = QGroupBox("Alice")
        answer_layout = QVBoxLayout(answer_box)
        answer_layout.addLayout(ask)
        answer_layout.addWidget(self.answer, 1)
        answer_layout.addWidget(self.answer_info)

        # Logs
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(MAX_LOG_LINES)
        self.logs.setFont(QFont("Consolas", 9))
        self.debug_box = QCheckBox("Logs détaillés")
        self.debug_box.setChecked(self.services.settings.log_level == "DEBUG")
        self.debug_box.toggled.connect(lambda on: set_level("DEBUG" if on else "INFO"))
        open_logs = QPushButton("Ouvrir le dossier des logs")
        open_logs.clicked.connect(self.open_log_folder)
        logs_bar = QHBoxLayout()
        logs_bar.addWidget(self.debug_box)
        logs_bar.addStretch(1)
        logs_bar.addWidget(open_logs)
        logs_box = QGroupBox("Journal")
        logs_layout = QVBoxLayout(logs_box)
        logs_layout.addWidget(self.logs, 1)
        logs_layout.addLayout(logs_bar)

        top = QSplitter(Qt.Orientation.Horizontal)
        top.addWidget(windows_box)
        top.addWidget(preview_box)
        top.addWidget(answer_box)
        top.setSizes([300, 520, 460])
        main = QSplitter(Qt.Orientation.Vertical)
        main.addWidget(top)
        main.addWidget(logs_box)
        main.setSizes([600, 200])

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addLayout(header)
        layout.addWidget(main, 1)
        self.setCentralWidget(root)

    def _attach_logs(self) -> None:
        self.log_bridge = LogBridge()
        self.log_bridge.line.connect(self.logs.appendPlainText)
        self.log_handler = QtLogHandler(self.log_bridge)
        self.log_handler.setFormatter(make_formatter())
        self.log_handler.addFilter(make_filter())
        logging.getLogger("alice").addHandler(self.log_handler)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self.hotkey is not None:
            self.hotkey.stop()
        self.stop_observation()
        logging.getLogger("alice").removeHandler(self.log_handler)
        log.info("Fermeture de la fenêtre principale")
        super().closeEvent(event)

    # --- état -----------------------------------------------------------------------------------

    def selected_window(self) -> WindowInfo | None:
        row = self.window_list.currentRow()
        return self.windows[row] if 0 <= row < len(self.windows) else None

    def _set_status(self, text: str) -> None:
        self.status.setText(text)

    def _update_state(self) -> None:
        has_selection = self.selected_window() is not None
        observing = self.observed is not None
        self.start_button.setText("Arrêter" if observing else "Démarrer")
        self.start_button.setEnabled(observing or has_selection)
        self.capture_button.setEnabled(observing and not self.busy)
        self.window_list.setEnabled(not observing)
        self.refresh_button.setEnabled(not observing)
        self.analyze_button.setText("Annuler" if self.busy else "Analyser")
        self.analyze_button.setEnabled(self.busy or observing or has_selection)
        if self.busy:
            return
        problem = self.services.model.check()
        if problem:
            self._set_status("⚠ " + problem)
        elif observing:
            mode = " (plein écran)" if self.observed and self.observed.fullscreen else ""
            self._set_status(f"Observation : {self.observed.title}{mode} — prête")  # type: ignore[union-attr]
        else:
            self._set_status("Sélectionne la fenêtre du jeu puis clique sur Démarrer.")

    # --- actions ------------------------------------------------------------------------------

    def refresh_windows(self) -> None:
        try:
            self.windows = self.services.capture.list_windows()
        except AliceError as exc:
            self.windows = []
            log.error("Liste des fenêtres impossible : %s", exc.detail)
            self._set_status("⚠ " + exc.user_message)
        previous = self.selected_window()
        self.window_list.clear()
        for window in self.windows:
            flag = "  [plein écran]" if window.fullscreen else ""
            item = QListWidgetItem(window.label + flag)
            item.setToolTip(f"HWND {window.handle} — PID {window.process_id}")
            self.window_list.addItem(item)
        if previous is not None:
            for row, window in enumerate(self.windows):
                if window.handle == previous.handle:
                    self.window_list.setCurrentRow(row)
        log.info("%d fenêtres détectées", len(self.windows))
        self._update_state()

    def toggle_observation(self) -> None:
        if self.observed is not None:
            self.stop_observation()
        else:
            self.start_observation()

    def start_observation(self) -> bool:
        window = self.selected_window()
        if window is None:
            self._set_status("Sélectionne d'abord une fenêtre.")
            return False
        self.observed = window
        log.info(
            "Fenêtre sélectionnée : « %s » (%s, PID %d, %s, écran %s%s)",
            window.title,
            window.exe_name or "?",
            window.process_id,
            f"{window.rect.width}x{window.rect.height}" if window.rect else "taille ?",
            window.monitor_index,
            ", plein écran" if window.fullscreen else "",
        )
        self._update_state()
        return True

    def stop_observation(self) -> None:
        if self.cancel_event is not None:
            self.cancel_event.set()
        if self.observed is not None:
            log.info("Observation arrêtée")
        self.generation += 1  # tout résultat en cours devient périmé
        self.observed = None
        self.busy = False
        self._update_state()

    def capture_now(self) -> None:
        if self.observed is None or self.busy:
            return
        window = self.observed
        self.busy = True
        self._set_status("Capture…")
        self._update_state()
        self._run(
            lambda emit: self.services.capture.capture(window), self._capture_done, self._failed
        )

    def analyze_or_cancel(self) -> None:
        if self.busy:
            if self.cancel_event is not None:
                self.cancel_event.set()
                log.info("Annulation demandée par le joueur")
            self.generation += 1
            self.busy = False
            self._set_status("Analyse annulée.")
            self.analyze_button.setText("Analyser")
            self._update_state()
            return
        if self.observed is None and not self.start_observation():
            return
        problem = self.services.model.check()
        if problem:
            self._set_status("⚠ " + problem)
            self.answer.setPlainText(problem)
            return
        self._start_analysis(self.observed, self.question.text())  # type: ignore[arg-type]

    def _start_analysis(self, window: WindowInfo, question: str) -> None:
        cancel = threading.Event()
        self.cancel_event = cancel
        self.busy = True
        self.answer.clear()
        self.answer_info.setText("")
        self._set_status("Capture puis analyse…")
        self._update_state()

        def work(emit):  # type: ignore[no-untyped-def]
            return self.services.analysis.analyze(
                window,  # type: ignore[arg-type]
                question,
                on_frame=lambda frame: emit(("frame", frame)),
                on_delta=lambda text: emit(("delta", text)),
                cancel=cancel,
            )

        self._run(work, self._analysis_done, self._failed, self._analysis_progress)

    # --- raccourci global ---------------------------------------------------------------------

    def _setup_hotkey(self) -> None:
        self.hotkey = None
        text = self.services.settings.hotkey_analyze
        if not text:
            self.hotkey_label.setText("Raccourci en jeu : désactivé")
            return
        from alice.ui.hotkey import GlobalHotkey

        try:
            hotkey = GlobalHotkey(text)
        except AliceError as exc:
            log.error("Raccourci invalide : %s", exc.user_message)
            self.hotkey_label.setText(f"Raccourci invalide : {text}")
            return
        hotkey.pressed.connect(self.hotkey_analyze)
        if hotkey.start():
            self.hotkey = hotkey
            self.hotkey_label.setText(f"En jeu : {text} = capture + analyse")
        else:
            self.hotkey_label.setText(f"Raccourci {text} indisponible (voir journal)")

    def hotkey_analyze(self) -> None:
        """Appui sur le raccourci en jeu : capture la fenêtre active et lance l'analyse."""
        if self.busy:
            log.info("Raccourci ignoré : une analyse est déjà en cours")
            return
        problem = self.services.model.check()
        if problem:
            self._set_status("⚠ " + problem)
            return
        window = self.services.capture.foreground_window() or self.observed
        if window is None:
            log.warning("Raccourci : aucune fenêtre de jeu active ni sélectionnée")
            self._set_status("Raccourci : mets le jeu au premier plan, puis réappuie.")
            return
        if self.observed is None or self.observed.handle != window.handle:
            self.observed = window
            log.info(
                "Raccourci : fenêtre active « %s » (%s%s)",
                window.title,
                window.exe_name or "?",
                ", plein écran" if window.fullscreen else "",
            )
        self._update_state()
        question = self.question.text().strip() or DEFAULT_HOTKEY_QUESTION
        self._start_analysis(window, question)

    def open_log_folder(self) -> None:
        folder = self.services.settings.log_dir
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # --- résultats ------------------------------------------------------------------------------

    def _run(self, fn, on_done, on_fail, on_progress=None) -> None:  # type: ignore[no-untyped-def]
        self.generation += 1
        task = Task(self.generation, fn)
        task.signals.finished.connect(lambda gen, value: self._settle(task, gen, on_done, value))
        task.signals.failed.connect(lambda gen, exc: self._settle(task, gen, on_fail, exc))
        if on_progress is not None:
            task.signals.progress.connect(
                lambda gen, item: on_progress(item) if gen == self.generation else None
            )
        self._live_tasks.add(task)
        self.pool.start(task)

    def _settle(self, task: Task, generation: int, handler, value: Any) -> None:  # type: ignore[no-untyped-def]
        self._live_tasks.discard(task)
        if generation != self.generation:
            log.debug("Résultat périmé ignoré (génération %d)", generation)
            return
        self.busy = False
        self._update_state()
        handler(value)

    def _show_frame(self, frame: Frame) -> None:
        self.preview.set_image(pixmap_from_image(frame.image))
        info = (
            f"{frame.width}×{frame.height} — {frame.backend} — "
            f"{frame.captured_at.astimezone():%H:%M:%S} — {frame.duration_ms} ms"
        )
        if frame.notes:
            info += "\n" + " ".join(frame.notes)
        self.preview_info.setText(info)

    def _capture_done(self, frame: Frame) -> None:
        self._show_frame(frame)
        self._set_status("Capture réussie.")

    def _analysis_progress(self, item: tuple[str, Any]) -> None:
        kind, value = item
        if kind == "frame":
            self._show_frame(value)
            self._set_status("Analyse en cours…")
        elif kind == "delta":
            cursor = self.answer.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(value)
            self.answer.setTextCursor(cursor)

    def _analysis_done(self, outcome: AnalysisOutcome) -> None:
        result = outcome.result
        self.answer.setMarkdown(result.text)
        first = (
            f"1er mot {result.first_token_ms} ms · " if result.first_token_ms is not None else ""
        )
        self.answer_info.setText(
            f"{result.provider}/{result.model} · {first}total {outcome.total_ms} ms · "
            f"profil {outcome.profile} · [{outcome.operation_id}]"
        )
        self._set_status("Réponse prête.")
        QApplication.alert(self)  # fait clignoter Alice dans la barre des tâches
        self.analysis_done.emit(outcome)

    def _failed(self, exc: Exception) -> None:
        if isinstance(exc, ProviderError) and exc.kind is ProviderErrorKind.CANCELLED:
            self._set_status("Analyse annulée.")
            return
        if isinstance(exc, AliceError):
            message = exc.user_message
        else:
            log.critical("Erreur inattendue", exc_info=exc)
            message = f"Erreur inattendue : {exc!r}. Détails dans le journal."
        self._set_status("⚠ " + message)
        self.answer.setPlainText(message)
        self.analysis_done.emit(exc)
