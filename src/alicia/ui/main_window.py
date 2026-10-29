"""Fenêtre principale d'ALICIA : HUD futuriste autour de son portrait, jamais bloquante."""

from __future__ import annotations

import html
import logging
import threading
from typing import Any

from PIL import Image
from PySide6.QtCore import Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QImage, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
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

from alicia import __version__
from alicia.app import Services
from alicia.core.ai.base import PreparedAudio
from alicia.core.analysis.service import AnalysisOutcome
from alicia.core.capture.models import Frame, WindowInfo
from alicia.core.errors import AliciaError, ProviderError, ProviderErrorKind
from alicia.core.logging_setup import make_filter, make_formatter, set_level
from alicia.ui.core_widget import AliciaCore
from alicia.ui.theme import CYAN, PINK, PINK_SOFT, STYLESHEET, title_font
from alicia.ui.workers import LogBridge, QtLogHandler, Task, VoiceBridge

log = logging.getLogger("alicia.ui")
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
        self.setMinimumSize(240, 135)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(
            "background: rgba(2,6,30,0.85); color:#5f6fa8; border:1px solid #24307a;"
            "border-radius:8px;"
        )
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


def _section(title: str) -> QLabel:
    label = QLabel(title)
    label.setObjectName("sectionTitle")
    return label


def _panel(*items) -> QFrame:  # type: ignore[no-untyped-def]
    """Cadre arrondi du HUD ; un élément peut être (widget, étirement)."""
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(8)
    for item in items:
        stretch = 0
        if isinstance(item, tuple):
            item, stretch = item
        if isinstance(item, QHBoxLayout | QVBoxLayout):
            layout.addLayout(item)
        else:
            layout.addWidget(item, stretch)
    return frame


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

        self.setWindowTitle(f"Alicia {__version__}" + (" — DÉMO" if services.demo else ""))
        self.resize(1360, 840)
        self.setMinimumSize(1000, 640)
        self._build_ui()
        if self.core.portrait is not None:
            self.setWindowIcon(QIcon(self.core.portrait))
        self._attach_logs()
        self.refresh_windows()
        self._update_state()
        self._setup_hotkey()
        # Modèles locaux chargés en arrière-plan : la 1re question orale n'attend pas.
        if self.services.transcriber is not None:
            self.services.transcriber.warm_up_async()
        if self.services.speaker is not None and self.services.settings.voice.speak_answers:
            self.services.speaker.warm_up_async()

    # --- construction -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setStyleSheet(STYLESHEET)

        # --- En-tête : nom, raccourcis, modèle -------------------------------------------------
        brand = QLabel("A · L · I · C · I · A")
        brand.setFont(title_font(15))
        brand.setStyleSheet(f"color:{PINK};")
        tagline = QLabel("copilote de jeu")
        tagline.setObjectName("muted")
        model = self.services.model
        self.provider_label = QLabel(f"IA · {model.provider} / {model.model}")
        self.provider_label.setObjectName("chip")
        self.hotkey_label = QLabel("")
        self.hotkey_label.setObjectName("chip")
        header = QHBoxLayout()
        header.addWidget(brand)
        header.addSpacing(10)
        header.addWidget(tagline)
        header.addStretch(1)
        header.addWidget(self.hotkey_label)
        header.addWidget(self.provider_label)

        # --- Colonne gauche : cible + vision -----------------------------------------------------
        self.window_list = QListWidget()
        self.window_list.setMaximumHeight(190)
        self.window_list.itemSelectionChanged.connect(self._update_state)
        self.window_list.itemDoubleClicked.connect(lambda _item: self.toggle_observation())
        self.refresh_button = QPushButton("↻")
        self.refresh_button.setToolTip("Actualiser la liste des fenêtres")
        self.refresh_button.setFixedWidth(40)
        self.refresh_button.clicked.connect(self.refresh_windows)
        self.start_button = QPushButton("Démarrer")
        self.start_button.clicked.connect(self.toggle_observation)
        self.capture_button = QPushButton("Capturer")
        self.capture_button.clicked.connect(self.capture_now)
        buttons = QHBoxLayout()
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.start_button, 1)
        buttons.addWidget(self.capture_button, 1)
        self.preview = PreviewLabel()
        self.preview_info = QLabel("")
        self.preview_info.setObjectName("muted")
        self.preview_info.setWordWrap(True)
        left = _panel(
            _section("CIBLE"),
            self.window_list,
            buttons,
            _section("VISION"),
            (self.preview, 1),
            self.preview_info,
        )
        left.setMinimumWidth(270)

        # --- Centre : ALICIA ---------------------------------------------------------------------
        self.core = AliciaCore()
        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setWordWrap(True)
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.addWidget(self.core, 1)
        center_layout.addWidget(self.status)

        # --- Droite : conversation ---------------------------------------------------------------
        self.asked_label = QLabel("")
        self.asked_label.setObjectName("asked")
        self.asked_label.setWordWrap(True)
        self.answer = QTextBrowser()
        self.answer.setOpenExternalLinks(True)
        self.answer.document().setDefaultStyleSheet(
            f"a {{ color: {CYAN}; }} b, strong {{ color: {PINK_SOFT}; }}"
        )
        self.answer.setPlaceholderText(
            "Maintiens F10 en jeu et parle-moi, ou tape ta question en bas."
        )
        self.sources_label = QLabel("")
        self.sources_label.setWordWrap(True)
        self.sources_label.setOpenExternalLinks(True)
        self.sources_label.setTextFormat(Qt.TextFormat.RichText)
        self.sources_label.setObjectName("muted")
        self.answer_info = QLabel("")
        self.answer_info.setObjectName("muted")
        self.answer_info.setWordWrap(True)
        self.web_box = QCheckBox("Recherche web")
        self.web_box.setToolTip("Recherche Google avant de répondre (méta, patch actuel)")
        self.web_box.setChecked(self.services.settings.ai.web_search)
        self.voice_box = QCheckBox("Voix")
        self.voice_box.setToolTip("ALICIA lit ses réponses à voix haute")
        self.voice_box.setChecked(self.services.settings.voice.speak_answers)
        self.voice_box.toggled.connect(lambda on: None if on else self.stop_voice())
        self.engine_box = QComboBox()
        self.engine_box.addItem("Edge (en ligne)", "edge")
        self.engine_box.addItem("Kokoro (locale)", "kokoro")
        self.engine_box.setCurrentIndex(
            max(0, self.engine_box.findData(self.services.settings.voice.tts_engine))
        )
        self.engine_box.currentIndexChanged.connect(self._change_voice_engine)
        self.stop_voice_button = QPushButton("■ Silence")
        self.stop_voice_button.setToolTip("Couper la voix d'ALICIA")
        self.stop_voice_button.clicked.connect(self.stop_voice)
        self.stop_voice_button.setEnabled(False)
        options = QHBoxLayout()
        options.addWidget(self.web_box)
        options.addWidget(self.voice_box)
        options.addWidget(self.engine_box)
        options.addStretch(1)
        options.addWidget(self.stop_voice_button)
        right = _panel(
            _section("CONVERSATION"),
            self.asked_label,
            (self.answer, 1),
            self.sources_label,
            self.answer_info,
            options,
        )
        right.setMinimumWidth(360)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([300, 520, 460])

        # --- Barre de question -------------------------------------------------------------------
        self.question = QLineEdit()
        self.question.setPlaceholderText(
            "Demande à ALICIA… (« quel objet pour Ashe ? », « monte le son »)"
        )
        self.question.returnPressed.connect(self.analyze_or_cancel)
        self.analyze_button = QPushButton("Analyser")
        self.analyze_button.setObjectName("primary")
        self.analyze_button.setDefault(True)
        self.analyze_button.clicked.connect(self.analyze_or_cancel)
        ask = QHBoxLayout()
        ask.addWidget(self.question, 1)
        ask.addWidget(self.analyze_button)

        # --- Journal (replié par défaut) ---------------------------------------------------------
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(MAX_LOG_LINES)
        self.debug_box = QCheckBox("Logs détaillés")
        self.debug_box.setChecked(self.services.settings.log_level == "DEBUG")
        self.debug_box.toggled.connect(lambda on: set_level("DEBUG" if on else "INFO"))
        open_logs = QPushButton("Ouvrir le dossier")
        open_logs.setObjectName("ghost")
        open_logs.clicked.connect(self.open_log_folder)
        logs_bar = QHBoxLayout()
        logs_bar.addWidget(self.debug_box)
        logs_bar.addStretch(1)
        logs_bar.addWidget(open_logs)
        self.logs_panel = _panel(_section("JOURNAL"), (self.logs, 1), logs_bar)
        self.logs_panel.setMinimumHeight(160)
        self.logs_panel.setVisible(False)
        self.logs_toggle = QPushButton("Journal ▸")
        self.logs_toggle.setObjectName("ghost")
        self.logs_toggle.clicked.connect(self.toggle_logs)
        footer = QHBoxLayout()
        footer.addWidget(self.logs_toggle)
        footer.addStretch(1)
        version = QLabel(f"v{__version__}" + (" · DÉMO" if self.services.demo else ""))
        version.setObjectName("muted")
        footer.addWidget(version)

        root = QWidget()
        root.setObjectName("root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 14, 18, 10)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addWidget(splitter, 1)
        layout.addLayout(ask)
        layout.addWidget(self.logs_panel)
        layout.addLayout(footer)
        self.setCentralWidget(root)

    def toggle_logs(self) -> None:
        visible = not self.logs_panel.isVisible()
        self.logs_panel.setVisible(visible)
        self.logs_toggle.setText("Journal ▾" if visible else "Journal ▸")

    def _core(self, state: str) -> None:
        """Met à jour le cœur animé (et sa source de niveau sonore)."""
        source = None
        if state == "listening" and self.services.recorder is not None:
            source = lambda: getattr(self.services.recorder, "level", 0.0) * 3.0  # noqa: E731
        elif state == "speaking" and self.services.speaker is not None:
            source = lambda: getattr(self.services.speaker, "level", 0.0) * 2.5  # noqa: E731
        self.core.set_state(state, source)

    def _core_settle(self) -> None:
        """Retour au repos, sauf si ALICIA est occupée ou parle."""
        speaker = self.services.speaker
        if self.busy:
            self._core("thinking")
        elif speaker is not None and getattr(speaker, "speaking", False):
            self._core("speaking")
        else:
            self._core("idle")

    def _attach_logs(self) -> None:
        self.log_bridge = LogBridge()
        self.log_bridge.line.connect(self.logs.appendPlainText)
        self.log_handler = QtLogHandler(self.log_bridge)
        self.log_handler.setFormatter(make_formatter())
        self.log_handler.addFilter(make_filter())
        logging.getLogger("alicia").addHandler(self.log_handler)
        self.voice_bridge = VoiceBridge()
        self.voice_bridge.state.connect(self._voice_state)
        self.voice_bridge.reminder.connect(self._reminder)
        if self.services.actions is not None:
            self.services.actions.on_reminder = self.voice_bridge.reminder.emit
        if self.services.speaker is not None:
            self.services.speaker.on_state = lambda state, msg: self.voice_bridge.state.emit(
                state, msg
            )

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        for hotkey in (self.hotkey, self.talk_hotkey):
            if hotkey is not None:
                hotkey.stop()
        if self.services.recorder is not None:
            self.services.recorder.cancel()
        if self.services.actions is not None:
            self.services.actions.stop()
        self.stop_voice()
        self.stop_observation()
        logging.getLogger("alicia").removeHandler(self.log_handler)
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
        except AliciaError as exc:
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
        if hasattr(self, "core"):
            self._core_settle()

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
            self._core_settle()
            return
        # Une demande d'action (« éteins le PC », « oui »…) ne demande ni jeu ni IA.
        if self.services.actions is not None and self.question.text().strip():
            reply = self.services.actions.route(self.question.text())
            if reply is not None:
                from alicia.core.analysis.service import AnalysisOutcome

                self._action_done(AnalysisOutcome("action", None, None, "", 0, action=reply))
                return
        if self.observed is None and not self.start_observation():
            return
        problem = self.services.model.check()
        if problem:
            self._set_status("⚠ " + problem)
            self.answer.setPlainText(problem)
            return
        self._start_analysis(self.observed, self.question.text())  # type: ignore[arg-type]

    def _start_analysis(
        self, window: WindowInfo, question: str, audio: PreparedAudio | None = None
    ) -> None:
        self.stop_voice()
        self._core("thinking")
        shown = "…" if audio is not None else (question.strip() or DEFAULT_HOTKEY_QUESTION)
        self.asked_label.setText(f"TOI  ›  {shown}")
        web_search = self.web_box.isChecked()
        spoken = self.voice_box.isChecked() and self.services.speaker is not None
        self.sources_label.setText("")
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
                on_transcript=lambda text: emit(("transcript", text)),
                cancel=cancel,
                audio=audio,
                web_search=web_search,
                spoken=spoken,
            )

        self._run(work, self._analysis_done, self._failed, self._analysis_progress)

    # --- raccourci global ---------------------------------------------------------------------

    def _setup_hotkey(self) -> None:
        self.hotkey = self._make_hotkey(self.services.settings.hotkey_analyze, False)
        self.talk_hotkey = None
        if self.services.recorder is not None:
            self.talk_hotkey = self._make_hotkey(self.services.settings.hotkey_talk, True)
        parts = []
        if self.hotkey is not None:
            self.hotkey.pressed.connect(self.hotkey_analyze)
            parts.append(f"{self.hotkey.text} = analyse")
        if self.talk_hotkey is not None:
            self.talk_hotkey.pressed.connect(self.talk_pressed)
            self.talk_hotkey.released.connect(self.talk_released)
            parts.append(f"{self.talk_hotkey.text} maintenu = parler")
        self.hotkey_label.setText(
            "En jeu : " + " · ".join(parts) if parts else "Raccourcis en jeu indisponibles"
        )

    def _make_hotkey(self, text: str, track_release: bool):  # type: ignore[no-untyped-def]
        if not text:
            return None
        from alicia.ui.hotkey import GlobalHotkey

        try:
            hotkey = GlobalHotkey(text, track_release=track_release)
        except AliciaError as exc:
            log.error("Raccourci invalide « %s » : %s", text, exc.user_message)
            return None
        return hotkey if hotkey.start() else None

    # --- voix -----------------------------------------------------------------------------------

    def talk_pressed(self) -> None:
        """Touche « parler » enfoncée en jeu : coupe Alicia si elle parle, ouvre le micro."""
        self.stop_voice()
        recorder = self.services.recorder
        if recorder is None or recorder.recording:
            return
        if self.busy:
            log.info("Parole ignorée : une analyse est déjà en cours")
            self._set_status("Patiente : Alicia analyse encore la question précédente.")
            return
        problem = self.services.model.check()
        if problem:
            self._set_status("⚠ " + problem)
            return
        try:
            recorder.start()
        except AliciaError as exc:
            log.error("Micro : %s", exc.detail)
            self._set_status("⚠ " + exc.user_message)
            return
        self._core("listening")
        self._set_status("🎙 Je t'écoute… relâche la touche quand tu as fini.")

    def talk_released(self) -> None:
        recorder = self.services.recorder
        if recorder is None or not recorder.recording:
            return
        try:
            audio = recorder.stop()
        except AliciaError as exc:
            log.warning("Question orale abandonnée : %s", exc.detail)
            self._set_status("⚠ " + exc.user_message)
            self._flash_error()
            return
        window = self.services.capture.foreground_window() or self.observed
        if window is None:
            self._set_status("Mets le jeu au premier plan, puis reparle.")
            return
        if self.observed is None or self.observed.handle != window.handle:
            self.observed = window
            self._update_state()
        self.question.setText("🎙 …")
        self._start_analysis(window, "", audio)

    def _change_voice_engine(self) -> None:
        speaker = self.services.speaker
        engine = self.engine_box.currentData()
        if speaker is None or not hasattr(speaker, "synthesizer"):
            return
        from dataclasses import replace

        from alicia.core.audio.speaker import make_synthesizer

        self.stop_voice()
        speaker.settings = replace(speaker.settings, tts_engine=engine)
        speaker.synthesizer = make_synthesizer(speaker.settings)
        speaker.warm_up_async()
        log.info("Voix d'Alicia : %s", engine)

    def _action_done(self, outcome: AnalysisOutcome) -> None:
        reply = outcome.action
        assert reply is not None
        if outcome.transcript is not None:
            self.question.setText(f"🎙 {outcome.transcript}")
        asked = outcome.transcript or self.question.text().strip()
        if asked:
            self.asked_label.setText(f"TOI  ›  {asked}")
        self.answer.setPlainText(reply.text)
        self.sources_label.setText("")
        self.answer_info.setText(f"Action sur le PC : {reply.intent} · [{outcome.operation_id}]")
        if reply.awaiting_confirmation:
            self._set_status(
                "Confirmation demandée : réponds « oui » ou « non » (F10 ou à l'écrit)."
            )
        else:
            self._set_status("Action traitée.")
        self.core.set_state("action")
        self._say(reply.text)
        QTimer.singleShot(1800, self._core_settle)
        self.analysis_done.emit(outcome)

    def _say(self, text: str) -> None:
        speaker = self.services.speaker
        if self.voice_box.isChecked() and speaker is not None and speaker.speak(text):
            self.stop_voice_button.setEnabled(True)

    def _flash_error(self) -> None:
        self._core("error")
        QTimer.singleShot(2500, self._core_settle)

    def _reminder(self, text: str) -> None:
        self.core.set_state("action")
        QTimer.singleShot(2500, self._core_settle)
        self.answer.setPlainText(text)
        self._set_status("⏰ " + text)
        QApplication.alert(self)
        self._say(text)

    def stop_voice(self) -> None:
        speaker = self.services.speaker
        if speaker is not None and speaker.speaking:
            speaker.stop()
        self.stop_voice_button.setEnabled(False)

    def _voice_state(self, state: str, message: str | None) -> None:
        if state == "speaking":
            self.stop_voice_button.setEnabled(True)
            self._core("speaking")
        else:
            self.stop_voice_button.setEnabled(False)
            if state == "error" and message:
                self._set_status("⚠ " + message)
                self._flash_error()
            else:
                self._core_settle()

    def _show_sources(self, result) -> None:  # type: ignore[no-untyped-def]
        notes = []
        if result.sources:
            links = " · ".join(
                f'<a style="color:{CYAN}" href="{html.escape(src.url)}">{html.escape(src.title)}</a>'
                for src in result.sources[:5]
            )
            notes.append(f"Sources web : {links}")
        if "search_disabled" in result.extra:
            notes.append("Recherche web refusée par le modèle : réponse sans recherche.")
        self.sources_label.setText("<br>".join(notes))

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
        elif kind == "transcript":
            self.question.setText(f"🎙 {value}")
            self.asked_label.setText(f"TOI  ›  🎙 {value}")
        elif kind == "delta":
            cursor = self.answer.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(value)
            self.answer.setTextCursor(cursor)

    def _analysis_done(self, outcome: AnalysisOutcome) -> None:
        if outcome.action is not None:
            self._action_done(outcome)
            return
        result = outcome.result
        assert result is not None
        self.answer.setMarkdown(result.text)
        first = (
            f"1er mot {result.first_token_ms} ms · " if result.first_token_ms is not None else ""
        )
        self.answer_info.setText(
            f"{result.provider}/{result.model} · {first}total {outcome.total_ms} ms · "
            f"profil {outcome.profile} · [{outcome.operation_id}]"
        )
        if outcome.transcript is not None:
            self.question.setText(f"🎙 {outcome.transcript}")
        self._show_sources(result)
        if self.voice_box.isChecked() and self.services.speaker is not None:
            if self.services.speaker.speak(result.text):
                self.stop_voice_button.setEnabled(True)
        fallback = result.extra.get("fallback_from")
        if fallback:
            self._set_status(
                f"Réponse prête — modèle de secours {result.model} ({fallback} saturé)."
            )
        else:
            self._set_status("Réponse prête.")
        QApplication.alert(self)  # fait clignoter Alicia dans la barre des tâches
        self._core_settle()
        self.analysis_done.emit(outcome)

    def _failed(self, exc: Exception) -> None:
        if isinstance(exc, ProviderError) and exc.kind is ProviderErrorKind.CANCELLED:
            self._set_status("Analyse annulée.")
            self._core_settle()
            return
        if isinstance(exc, AliciaError):
            message = exc.user_message
        else:
            log.critical("Erreur inattendue", exc_info=exc)
            message = f"Erreur inattendue : {exc!r}. Détails dans le journal."
        self._set_status("⚠ " + message)
        self.answer.setPlainText(message)
        self._flash_error()
        self.analysis_done.emit(exc)
