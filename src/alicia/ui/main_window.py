"""Fenêtre principale d'ALICIA : HUD futuriste autour de son portrait, jamais bloquante."""

from __future__ import annotations

import html
import logging
import sys
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
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from alicia import __version__
from alicia.app import Services
from alicia.core.ai.base import PreparedAudio
from alicia.core.analysis.service import AnalysisOutcome
from alicia.core.capture.models import Frame, WindowInfo
from alicia.core.config import state_dir
from alicia.core.errors import AliciaError, ProviderError, ProviderErrorKind
from alicia.core.logging_setup import make_filter, make_formatter, set_level
from alicia.core.update import UpdateInfo, Updater, install_root
from alicia.games.store import GameStore
from alicia.ui.core_widget import AliciaCore
from alicia.ui.games_page import GamesPage
from alicia.ui.orb import OrbWindow
from alicia.ui.shortcuts_page import ShortcutsPage
from alicia.ui.theme import CYAN, PINK, PINK_SOFT, STYLESHEET, title_font
from alicia.ui.workers import LogBridge, QtLogHandler, Task, VoiceBridge

log = logging.getLogger("alicia.ui")
MAX_LOG_LINES = 3000
NOTICES = ("⚠", "Patiente", "Mets le jeu", "Raccourci :", "Confirmation demandée")
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


def _muted_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
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
        self.wake = None  # WakeListener, créé quand le réveil vocal est activé
        self.ollama_runtime = None  # OllamaRuntime quand l'IA locale est choisie
        self.update_info: UpdateInfo | None = None
        self._updating = False
        self.updater = self._make_updater()
        self._build_orb()
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
        self.game_store = GameStore()

        # --- En-tête : nom, raccourcis, modèle -------------------------------------------------
        brand = QLabel("A · L · I · C · I · A")
        brand.setFont(title_font(15))
        brand.setStyleSheet(f"color:{PINK};")
        tagline = QLabel("copilote de jeu")
        tagline.setObjectName("muted")
        model = self.services.model
        self.provider_label = QPushButton(f"IA · {model.provider} / {model.model}")
        self.provider_label.setToolTip("Choisir l'IA d'ALICIA et coller sa clé")
        self.provider_label.clicked.connect(self.open_setup)
        self.hotkey_label = QLabel("")
        self.hotkey_label.setObjectName("chip")
        self.nav_console = QPushButton("◈  ALICIA")
        self.nav_games = QPushButton("▦  JEUX")
        self.nav_keys = QPushButton("⌨  RACCOURCIS")
        self.nav_keys.setToolTip("Changer la touche pour parler à ALICIA ; commandes vocales")
        for button, index in ((self.nav_console, 0), (self.nav_games, 1), (self.nav_keys, 2)):
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, i=index: self.show_page(i))
        self.nav_console.setChecked(True)
        self.nav_games.setToolTip("Tes jeux et leurs sites de référence")
        header = QHBoxLayout()
        header.addWidget(brand)
        header.addSpacing(10)
        header.addWidget(tagline)
        header.addSpacing(24)
        header.addWidget(self.nav_console)
        header.addWidget(self.nav_games)
        header.addWidget(self.nav_keys)
        header.addStretch(1)
        header.addWidget(self.hotkey_label)
        header.addWidget(self.provider_label)
        self.orb_button = QPushButton("◉  Mode bulle")
        self.orb_button.setToolTip(
            "Ne garder que le rond d'ALICIA à l'écran (ses réponses s'affichent à côté)"
        )
        self.orb_button.clicked.connect(self.show_orb)
        self.update_button = QPushButton("⟳  MAJ")
        self.update_button.setToolTip("Vérifier et installer la dernière version d'ALICIA")
        self.update_button.clicked.connect(self.update_now)
        header.addWidget(self.update_button)
        header.addWidget(self.orb_button)

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
        # La fenêtre du jeu se choisit dans l'onglet Jeux : F9 et F10 la trouvent seuls.
        self.target_panel = _panel(
            _section("FENÊTRE DU JEU"),
            _muted_label(
                "Inutile en jeu : F9 et F10 prennent la fenêtre au premier plan. "
                "Choisis-la ici pour poser des questions écrites depuis ce panneau."
            ),
            (self.window_list, 1),
            buttons,
        )
        self.window_list.setMaximumHeight(16777215)
        left = _panel(
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
        self.wake_box = QCheckBox("Réveil « Alicia »")
        self.wake_box.setToolTip(
            "Commence ta phrase par « Alicia » pour lui parler sans F10. "
            "Tout reste sur ton PC tant que le mot n'est pas dit."
        )
        self.wake_box.setChecked(
            self.services.settings.voice.wake_word and self.services.recorder is not None
        )
        self.wake_box.setEnabled(self.services.recorder is not None)
        self.wake_box.toggled.connect(self.set_wake)
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
        self.game_box = QComboBox()
        self.game_box.setToolTip(
            "Le jeu auquel tu joues : ALICIA connaît son contexte et cherche d'abord sur ses "
            "sites de référence. « Auto » le reconnaît à la fenêtre."
        )
        self._fill_games()
        self.game_box.currentIndexChanged.connect(self._change_game)
        for combo in (self.game_box, self.engine_box):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        game_row = QHBoxLayout()
        game_row.addWidget(self.game_box, 1)
        game_row.addWidget(self.stop_voice_button)
        switches = QHBoxLayout()
        switches.addWidget(self.web_box)
        switches.addWidget(self.voice_box)
        switches.addWidget(self.wake_box)
        switches.addStretch(1)
        switches.addWidget(self.engine_box)
        options = QVBoxLayout()
        options.setSpacing(8)
        options.addLayout(game_row)
        options.addLayout(switches)
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
        # --- Pages : console d'ALICIA / onglet Jeux ----------------------------------------------
        console = QWidget()
        console_layout = QVBoxLayout(console)
        console_layout.setContentsMargins(0, 0, 0, 0)
        console_layout.setSpacing(12)
        console_layout.addWidget(splitter, 1)
        console_layout.addLayout(ask)
        self.games_page = GamesPage(
            self.game_store,
            active_game=self._active_game_key,
            current_window=lambda: self.observed,
            side_panel=self.target_panel,
        )
        self.games_page.games_changed.connect(self._games_changed)
        self.games_page.use_game.connect(self._select_game)
        self.pages = QStackedWidget()
        self.pages.addWidget(console)
        self.pages.addWidget(self.games_page)
        settings = self.services.settings
        self.hotkey_texts = {"analyze": settings.hotkey_analyze, "talk": settings.hotkey_talk}
        self.shortcuts_page = ShortcutsPage(self.hotkey_texts)
        self.shortcuts_page.change_requested.connect(self.change_hotkey)
        self.shortcuts_page.capturing.connect(self._suspend_hotkeys)
        self.pages.addWidget(self.shortcuts_page)

        layout.addLayout(header)
        layout.addWidget(self.pages, 1)
        layout.addWidget(self.logs_panel)
        layout.addLayout(footer)
        self.setCentralWidget(root)

    def show_page(self, index: int) -> None:
        """0 = console d'ALICIA, 1 = onglet Jeux (toujours ouvert sur la liste)."""
        self.pages.setCurrentIndex(index)
        self.nav_console.setChecked(index == 0)
        self.nav_games.setChecked(index == 1)
        self.nav_keys.setChecked(index == 2)
        if index == 1:
            self.games_page.show_list()

    def _active_game_key(self) -> str:
        """Le jeu choisi, sinon celui reconnu dans la fenêtre observée."""
        key = self.services.analysis.game_profile
        if key != "auto":
            return key
        from alicia.games.profiles import resolve_profile

        return resolve_profile(self.observed).key if self.observed is not None else ""

    def _select_game(self, key: str) -> None:
        self.game_box.setCurrentIndex(max(0, self.game_box.findData(key)))

    def _games_changed(self) -> None:
        """Un jeu a été ajouté, modifié ou supprimé : menus du panneau et du rond à jour."""
        current = self.services.analysis.game_profile
        if current not in self.game_store.profiles and current != "auto":
            current = "auto"
        self.game_box.blockSignals(True)
        self.game_box.clear()
        self._fill_games(current)
        self.game_box.blockSignals(False)
        self.services.analysis.game_profile = self.game_box.currentData()
        self._sync_orb_games()

    def _sync_orb_games(self) -> None:
        self.orb.games = [
            (self.game_box.itemData(i), self.game_box.itemText(i))
            for i in range(self.game_box.count())
        ]
        self.orb.current_game = self.services.analysis.game_profile

    def _build_orb(self) -> None:
        settings = self.services.settings
        self.orb = OrbWindow(settings.orb_size, state_dir() / "orb.json")
        self.bubble = self.orb.bubble
        self.orb.open_panel.connect(self.show_panel)
        self.orb.stop_voice.connect(self.stop_voice)
        self.orb.quit_requested.connect(self.quit_app)
        self._sync_orb_games()
        self.orb.game_chosen.connect(self._select_game)
        self.orb.update_requested.connect(self.update_now)
        self.orb.setup_requested.connect(self.open_setup)
        self.orb.wake_toggled.connect(self.wake_box.setChecked)
        self.orb_mode = settings.ui_mode == "orb"

    def start(self) -> None:
        """Affichage au lancement, selon [ui] mode."""
        if self.orb_mode:
            self.show_orb()
        else:
            self.show_panel()
        if self.wake_box.isChecked() and not self.services.demo:
            self.set_wake(True)
        if not self.services.demo and self._needs_key():
            QTimer.singleShot(600, self.open_setup)  # premier lancement : choisir son IA
        if not self.services.demo:
            self.prepare_ollama()
        if self.updater is not None and self.services.settings.update.check_on_start:
            if not self.services.demo:
                QTimer.singleShot(4000, lambda: self.check_update(interactive=False))

    # --- choix de l'IA et de la clé -------------------------------------------------------------

    def _needs_key(self) -> bool:
        ai = self.services.settings.ai
        return (ai.provider == "gemini" and not ai.gemini.api_key) or (
            ai.provider == "openai" and not ai.openai.api_key
        )

    def open_setup(self) -> None:
        from alicia.ui.setup_dialog import SetupDialog

        ai = self.services.settings.ai
        dialog = SetupDialog(
            ai.provider,
            {"gemini": bool(ai.gemini.api_key), "openai": bool(ai.openai.api_key)},
            self if self.isVisible() else None,
            gemini=ai.gemini,
            openai=ai.openai,
        )
        if dialog.exec() and dialog.choice is not None:
            self.apply_ai_choice(*dialog.choice)

    def apply_ai_choice(self, provider: str, key: str) -> None:
        """Enregistre le choix (clé dans %APPDATA%\\Alicia\\.env) et change d'IA sans redémarrer."""
        from alicia.core.ai.factory import create_model
        from alicia.core.config import load_settings
        from alicia.core.user_config import set_env, set_value

        try:
            if key:
                from alicia.ui.setup_dialog import KEY_PROVIDERS

                set_env(KEY_PROVIDERS[provider].env, key)
            set_value("ai", "provider", provider)
            settings = load_settings()
        except (OSError, ValueError, AliciaError) as exc:
            log.error("Choix de l'IA non enregistré : %r", exc)
            self._notify("⚠ Impossible d'enregistrer ce choix : voir le journal.")
            return
        model = create_model(settings.ai)
        self.services.settings = settings
        self.services.model = model
        self.services.analysis.model = model
        self.provider_label.setText(f"IA · {model.provider} / {model.model}")
        log.info("IA choisie : %s/%s", model.provider, model.model)
        problem = model.check()
        self._notify("⚠ " + problem if problem else "IA prête ✓ Maintiens F10 ou dis « Alicia… »")
        self._update_state()
        self.prepare_ollama()

    def prepare_ollama(self) -> None:
        """IA locale choisie : démarre Ollama s'il ne tourne pas, télécharge son modèle au besoin."""
        ai = self.services.settings.ai
        if ai.provider != "ollama":
            return
        from alicia.core.ai.providers.ollama_runtime import OllamaRuntime

        if self.ollama_runtime is None or self.ollama_runtime.model != ai.ollama.model:
            self.ollama_runtime = OllamaRuntime(ai.ollama.base_url, ai.ollama.model)
        runtime = self.ollama_runtime

        def work(emit):  # type: ignore[no-untyped-def]
            started = runtime.ensure_running()
            if started:
                emit(("status", "Ollama démarré ✓"))
            if not runtime.has_model():
                emit(("status", f"Téléchargement du modèle « {runtime.model} » (plusieurs Go)…"))
                runtime.pull(lambda percent: emit(("pull", percent)))
                return "pulled"
            return "started" if started else "ready"

        def progress(item) -> None:  # type: ignore[no-untyped-def]
            kind, value = item
            if kind == "pull":
                text = f"Téléchargement du modèle IA locale : {value} %"
                self.status.setText(text)
                if value % 10 == 0:
                    self._notify(text)
            else:
                self._notify(value)

        def done(result: str) -> None:
            if result == "pulled":
                self._notify("IA locale prête ✓ Maintiens F10 ou dis « Alicia… »")
            elif result == "started":
                self._notify("Ollama démarré ✓ IA locale prête")

        def failed(exc: Exception) -> None:
            message = exc.user_message if isinstance(exc, AliciaError) else repr(exc)
            log.error("Ollama : %s", exc.detail if isinstance(exc, AliciaError) else repr(exc))
            self._notify("⚠ " + message)

        task = Task(0, work)
        task.signals.progress.connect(lambda _g, item: progress(item))
        task.signals.finished.connect(
            lambda _g, value: (self._live_tasks.discard(task), done(value))
        )
        task.signals.failed.connect(lambda _g, exc: (self._live_tasks.discard(task), failed(exc)))
        self._live_tasks.add(task)
        self.pool.start(task)

    # --- réveil vocal « Alicia » ----------------------------------------------------------------

    def set_wake(self, on: bool) -> None:
        if hasattr(self, "orb"):
            self.orb.wake_on = on
        if not on:
            if self.wake is not None:
                self.wake.stop()
            return
        if self.services.recorder is None or self.services.demo:
            return
        if self.wake is None:
            from alicia.core.audio.wake import WakeListener, WhisperWakeDetector

            voice = self.services.settings.voice
            detector = WhisperWakeDetector(voice.wake_model)
            detector.warm_up_async()  # premier lancement : télécharge le petit modèle (~140 Mo)
            self.wake = WakeListener(
                detector,
                on_wake=self.voice_bridge.wake.emit,
                on_command=self.voice_bridge.wake_command.emit,
                on_cancel=self.voice_bridge.wake_cancel.emit,
                paused=self._wake_paused,
                stop_only=self._wake_stop_only,
                on_stop=self.voice_bridge.wake_stop.emit,
                device=voice.input_device,
                sample_rate=voice.sample_rate,
            )
        try:
            self.wake.start()
        except AliciaError as exc:
            log.error("Réveil vocal indisponible : %s", exc.detail)
            self._notify("⚠ " + exc.user_message)
            self.wake_box.blockSignals(True)
            self.wake_box.setChecked(False)
            self.wake_box.blockSignals(False)
            self.orb.wake_on = False

    def _wake_paused(self) -> bool:
        """Micro réservé à la touche « parler » pendant qu'elle est maintenue."""
        recorder = self.services.recorder
        return bool(recorder is not None and recorder.recording)

    def _wake_stop_only(self) -> bool:
        """Pendant qu'ALICIA analyse ou parle, seul « Alicia, stop » est écouté."""
        speaker = self.services.speaker
        return bool(self.busy or (speaker is not None and getattr(speaker, "speaking", False)))

    def voice_stop(self) -> None:
        """« Alicia, stop » : elle se tait et annule l'analyse en cours."""
        self.stop_voice()
        if self.busy:
            self.analyze_or_cancel()  # occupée : ce bouton annule
        self._core_settle()
        self._set_status("D'accord, j'arrête.")
        if self._bubble_active() and self.bubble.isVisible():
            self.bubble.fade_out()

    def _wake_heard(self) -> None:
        self._core("listening")
        self._set_status("🎙 Je t'écoute…")
        if self._bubble_active():
            self.bubble.ask("🎙 …")

    def _wake_command(self, audio: PreparedAudio) -> None:
        if self.busy:
            return
        window = self.services.capture.foreground_window() or self.observed
        if window is not None and (self.observed is None or self.observed.handle != window.handle):
            self.observed = window
            self._update_state()
        self.question.setText("🎙 …")
        self._start_analysis(window, "", audio)  # type: ignore[arg-type]

    def _wake_cancel(self, reason: str) -> None:
        log.info("Réveil sans demande : %s", reason)
        self._core_settle()
        self._set_status("Je n'ai pas entendu de demande après « Alicia ».")
        if self._bubble_active() and self.bubble.isVisible():
            self.bubble.fade_out()

    # --- mise à jour ----------------------------------------------------------------------------

    def _make_updater(self) -> Updater | None:
        root = install_root()
        update = self.services.settings.update
        if root is None or not update.repo or not update.branch:
            self.update_button.setEnabled(False)
            self.update_button.setToolTip(
                "Mise à jour automatique indisponible pour cette installation"
            )
            return None
        return Updater(root, update.repo, update.branch, update.token)

    def _background(self, fn, on_done, on_fail) -> None:  # type: ignore[no-untyped-def]
        task = Task(0, lambda _emit: fn())
        task.signals.finished.connect(
            lambda _g, value: (self._live_tasks.discard(task), on_done(value))
        )
        task.signals.failed.connect(lambda _g, exc: (self._live_tasks.discard(task), on_fail(exc)))
        self._live_tasks.add(task)
        self.pool.start(task)

    def _notify(self, text: str) -> None:
        """Message court : barre d'état du panneau, ou bulle en mode bulle."""
        self.status.setText(text)
        if self._bubble_active():
            self.bubble.notice(text)

    def update_now(self) -> None:
        if self.updater is None or self._updating:
            return
        if self.update_info is not None:
            self._confirm_update(self.update_info)
        else:
            self.check_update(interactive=True)

    def check_update(self, interactive: bool = True) -> None:
        if self.updater is None or self._updating:
            return
        self._updating = True
        self.update_button.setText("⟳  Vérification…")
        if interactive:
            self._notify("Je regarde s'il y a une nouvelle version…")
        updater = self.updater

        def done(info: UpdateInfo | None) -> None:
            self._updating = False
            self.update_info = info
            if info is None:
                self._set_update_button(False)
                if interactive:
                    self._notify("ALICIA est déjà à jour ✓")
                return
            self._set_update_button(True)
            if interactive:
                self._confirm_update(info)
            else:
                self._notify(
                    "Une nouvelle version d'ALICIA est prête : bouton MAJ (ou clic droit sur le rond)."
                )

        def failed(exc: Exception) -> None:
            self._updating = False
            self._set_update_button(False)
            detail = exc.detail if isinstance(exc, AliciaError) else repr(exc)
            log.warning("Vérification de mise à jour impossible : %s", detail)
            if interactive:
                message = exc.user_message if isinstance(exc, AliciaError) else str(exc)
                self._notify("⚠ " + message)

        self._background(updater.check, done, failed)

    def _set_update_button(self, available: bool) -> None:
        self.update_button.setText("⟳  MAJ dispo" if available else "⟳  MAJ")
        self.update_button.setObjectName("primary" if available else "")
        self.update_button.style().unpolish(self.update_button)
        self.update_button.style().polish(self.update_button)

    def _confirm_update(self, info: UpdateInfo) -> None:
        when = info.date[:10] if info.date else ""
        answer = QMessageBox.question(
            self if self.isVisible() else None,
            "Mise à jour d'ALICIA",
            f"Nouvelle version disponible ({info.short}{', ' + when if when else ''}) :\n\n"
            f"« {info.title} »\n\nL'installer maintenant ? ALICIA redémarrera toute seule.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.install_update(info)

    def install_update(self, info: UpdateInfo) -> None:
        if self.updater is None or self._updating:
            return
        self._updating = True
        self.update_button.setText("⟳  Installation…")
        self._notify("Je télécharge ma nouvelle version…")
        updater = self.updater

        def done(result) -> None:  # type: ignore[no-untyped-def]
            self._updating = False
            self.update_info = None
            self._set_update_button(False)
            extra = (
                "\nLes composants Python seront mis à jour au redémarrage (fenêtre de progression)."
                if result.dependencies_changed
                else ""
            )
            log.info("Redémarrage après mise à jour (%d fichiers)", len(result.changed))
            QMessageBox.information(
                self if self.isVisible() else None,
                "Mise à jour installée",
                f"Version {info.short} installée ({len(result.changed)} fichier(s) modifié(s)).{extra}\n\n"
                "ALICIA redémarre.",
            )
            self.restart(show_console=result.dependencies_changed)

        def failed(exc: Exception) -> None:
            self._updating = False
            self._set_update_button(True)
            detail = exc.detail if isinstance(exc, AliciaError) else repr(exc)
            log.error("Mise à jour échouée : %s", detail)
            message = exc.user_message if isinstance(exc, AliciaError) else str(exc)
            self._notify("⚠ Mise à jour échouée : " + message)

        self._background(lambda: updater.apply(info), done, failed)

    def restart(self, show_console: bool = False) -> None:
        """Relance ALICIA par Lancer_Alicia.bat (qui met à jour les dépendances au besoin)."""
        import subprocess
        import sys

        root = self.updater.root if self.updater is not None else None
        launcher = root / "Lancer_Alicia.bat" if root is not None else None
        if sys.platform == "win32" and launcher is not None and launcher.is_file():
            # Petite pause (ping) : les raccourcis F9/F10 doivent être libérés avant la relance.
            # Terminal visible seulement si des composants Python sont à mettre à jour.
            flags = (
                subprocess.CREATE_NEW_CONSOLE  # type: ignore[attr-defined]
                if show_console
                else subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
            )
            subprocess.Popen(
                f'cmd /c "ping -n 3 127.0.0.1 >nul & call "{launcher}""',
                cwd=str(root),
                creationflags=flags,
            )
        else:
            log.warning("Redémarrage automatique indisponible : relance ALICIA à la main.")
        self.quit_app()

    def show_orb(self) -> None:
        self.orb_mode = True
        self.hide()
        self.orb.show()
        self._core_settle()
        log.info("Mode bulle : seul le rond d'ALICIA est affiché")

    def show_panel(self) -> None:
        self.orb_mode = False
        self.orb.hide()
        self.show()
        self.raise_()
        self.activateWindow()
        self._core_settle()

    def quit_app(self) -> None:
        self.close()
        QApplication.quit()

    def _bubble_active(self) -> bool:
        return self.orb.isVisible()

    def _bubble_linger(self, text: str) -> int:
        """Durée d'affichage après la fin de la réponse (lecture à l'écran)."""
        return int(min(20000, max(5000, len(text) * 55)))

    def _bubble_finish(self, text: str, spoken: bool) -> None:
        """Réponse finale : la bulle reste pendant la voix, puis s'efface."""
        if not self._bubble_active():
            return
        self.bubble.set_answer(text)
        if not spoken:
            self.bubble.hide_after(self._bubble_linger(text))

    def toggle_logs(self) -> None:
        visible = not self.logs_panel.isVisible()
        self.logs_panel.setVisible(visible)
        self.logs_toggle.setText("Journal ▾" if visible else "Journal ▸")

    def _core(self, state: str) -> None:
        """Met à jour le cœur animé (et sa source de niveau sonore)."""
        source = None
        recorder = self.services.recorder
        if state == "listening" and recorder is not None and recorder.recording:
            source = lambda: getattr(recorder, "level", 0.0) * 3.0  # noqa: E731
        elif state == "listening" and self.wake is not None:
            wake = self.wake
            source = lambda: wake.level * 2.0  # noqa: E731
        elif state == "speaking" and self.services.speaker is not None:
            source = lambda: getattr(self.services.speaker, "level", 0.0) * 2.5  # noqa: E731
        self.core.set_state(state, source)
        if hasattr(self, "orb"):
            self.orb.core.set_state(state, source)

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
        self.voice_bridge.wake.connect(self._wake_heard)
        self.voice_bridge.wake_command.connect(self._wake_command)
        self.voice_bridge.wake_cancel.connect(self._wake_cancel)
        self.voice_bridge.wake_stop.connect(self.voice_stop)
        if self.services.actions is not None:
            self.services.actions.on_reminder = self.voice_bridge.reminder.emit
        if self.services.speaker is not None:
            self.services.speaker.on_state = lambda state, msg: self.voice_bridge.state.emit(
                state, msg
            )

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]  # noqa: N802
        if self.wake is not None:
            self.wake.stop()
        if self.ollama_runtime is not None:
            self.ollama_runtime.stop()
        for hotkey in (self.hotkey, self.talk_hotkey):
            if hotkey is not None:
                hotkey.stop()
        if self.services.recorder is not None:
            self.services.recorder.cancel()
        if self.services.actions is not None:
            self.services.actions.stop()
        self.stop_voice()
        self.stop_observation()
        self.orb.close()
        logging.getLogger("alicia").removeHandler(self.log_handler)
        log.info("Fermeture de la fenêtre principale")
        super().closeEvent(event)

    # --- état -----------------------------------------------------------------------------------

    def selected_window(self) -> WindowInfo | None:
        row = self.window_list.currentRow()
        return self.windows[row] if 0 <= row < len(self.windows) else None

    def _set_status(self, text: str) -> None:
        self.status.setText(text)
        # En mode bulle, les avertissements et consignes passent par la bulle.
        if hasattr(self, "orb") and self._bubble_active() and text.startswith(NOTICES):
            self.bubble.notice(text.removeprefix("⚠ "))

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
            self._set_status(
                "En jeu : maintiens F10 pour me parler, ou F9 pour une analyse rapide."
            )

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
            self._set_status(
                "Aucune fenêtre de jeu : utilise F9/F10 en jeu, ou choisis-la dans l'onglet Jeux."
            )
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
        if self._bubble_active():
            self.bubble.ask("🎙 …" if audio is not None else shown)
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
        from alicia.ui.hotkey import hotkey_label

        self.hotkey = self._make_hotkey(self.hotkey_texts["analyze"], False)
        self.talk_hotkey = None
        if self.services.recorder is not None:
            self.talk_hotkey = self._make_hotkey(self.hotkey_texts["talk"], True)
        parts = []
        if self.hotkey is not None:
            self.hotkey.pressed.connect(self.hotkey_analyze)
            parts.append(f"{hotkey_label(self.hotkey.text)} = analyse")
        if self.talk_hotkey is not None:
            self.talk_hotkey.pressed.connect(self.talk_pressed)
            self.talk_hotkey.released.connect(self.talk_released)
            parts.append(f"{hotkey_label(self.talk_hotkey.text)} maintenu = parler")
        self.hotkey_label.setText(
            "En jeu : " + " · ".join(parts) if parts else "Raccourcis en jeu indisponibles"
        )
        for action, hotkey in (("analyze", self.hotkey), ("talk", self.talk_hotkey)):
            text = self.hotkey_texts[action]
            if hotkey is not None:
                state = "✓ actif"
            elif not text:
                state = "désactivé"
            elif sys.platform == "win32":
                state = "⚠ indisponible : touche déjà prise par un autre programme ?"
            else:
                state = "raccourcis globaux : Windows seulement"
            self.shortcuts_page.set_state(action, state, text)

    def _stop_hotkeys(self) -> None:
        for hotkey in (self.hotkey, self.talk_hotkey):
            if hotkey is not None:
                hotkey.stop()
        self.hotkey = self.talk_hotkey = None

    def _suspend_hotkeys(self, capturing: bool) -> None:
        """Pendant qu'on choisit une touche, F9/F10 ne déclenchent rien."""
        if capturing:
            self._stop_hotkeys()
        else:
            self._setup_hotkey()

    def change_hotkey(self, action: str, text: str) -> None:
        from alicia.core.user_config import set_value
        from alicia.ui.hotkey import hotkey_label, parse_hotkey

        other = "analyze" if action == "talk" else "talk"
        try:
            parse_hotkey(text)
        except AliciaError as exc:
            self.shortcuts_page.set_state(action, "⚠ " + exc.user_message)
            return
        if text.lower() == self.hotkey_texts[other].lower():
            self.shortcuts_page.set_state(
                action, f"⚠ {hotkey_label(text)} sert déjà à l'autre raccourci."
            )
            return
        self._stop_hotkeys()
        self.hotkey_texts[action] = text
        try:
            set_value("hotkeys", action, text)
        except (OSError, ValueError) as exc:
            log.error("Raccourci non enregistré : %r", exc)
        self._setup_hotkey()
        log.info("Raccourci « %s » : %s", action, text)

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

    def _fill_games(self, current: str | None = None) -> None:
        self.game_box.addItem("Jeu : auto", "auto")
        for profile in self.game_store.games():
            self.game_box.addItem(profile.name, profile.key)
        self.game_box.addItem("Autre jeu", "generic")
        current = current or self.services.analysis.game_profile
        self.game_box.setCurrentIndex(max(0, self.game_box.findData(current)))

    def _change_game(self) -> None:
        key = self.game_box.currentData()
        self.services.analysis.game_profile = key
        if hasattr(self, "orb"):
            self.orb.current_game = key
        log.info("Jeu choisi : %s", self.game_box.currentText())

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
        if self._bubble_active():
            self.bubble.ask(asked)
        self.sources_label.setText("")
        self.answer_info.setText(f"Action sur le PC : {reply.intent} · [{outcome.operation_id}]")
        if reply.awaiting_confirmation:
            self._set_status(
                "Confirmation demandée : réponds « oui » ou « non » (F10 ou à l'écrit)."
            )
        else:
            self._set_status("Action traitée.")
        self._core("action")
        self._bubble_finish(reply.text, self._say(reply.text))
        QTimer.singleShot(1800, self._core_settle)
        self.analysis_done.emit(outcome)

    def _say(self, text: str) -> bool:
        speaker = self.services.speaker
        if self.voice_box.isChecked() and speaker is not None and speaker.speak(text):
            self.stop_voice_button.setEnabled(True)
            return True
        return False

    def _flash_error(self) -> None:
        self._core("error")
        QTimer.singleShot(2500, self._core_settle)

    def _reminder(self, text: str) -> None:
        self._core("action")
        QTimer.singleShot(2500, self._core_settle)
        self.answer.setPlainText(text)
        self._set_status("⏰ " + text)
        QApplication.alert(self)
        if self._bubble_active():
            self.bubble.ask("")
        self._bubble_finish("⏰ " + text, self._say(text))

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
            # Elle a fini de parler : la bulle s'efface peu après (sauf nouvelle question).
            if self._bubble_active() and not self.busy and self.bubble.isVisible():
                self.bubble.hide_after(4000)

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
            if self._bubble_active():
                self.bubble.set_question(f"🎙 {value}")
        elif kind == "delta":
            cursor = self.answer.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(value)
            self.answer.setTextCursor(cursor)
            if self._bubble_active():
                self.bubble.append(value)

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
        self._bubble_finish(result.text, self._say(result.text))
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
