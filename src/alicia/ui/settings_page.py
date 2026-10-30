"""Onglet « Réglages » : micro, voix d'ALICIA, IA, démarrage et raccourcis, au même endroit.

Chaque changement est appliqué tout de suite et enregistré dans %APPDATA%\\Alicia\\alicia.toml.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from alicia.core.config import VoiceSettings
from alicia.core.persona import PERSONAS
from alicia.core.persona import current as current_persona
from alicia.ui.shortcuts_page import ShortcutsPage
from alicia.ui.theme import PINK, title_font

EDGE_VOICES = (
    ("fr-FR-DeniseNeural", "Denise (France) — douce"),
    ("fr-FR-VivienneMultilingualNeural", "Vivienne (France) — naturelle"),
    ("fr-FR-EloiseNeural", "Éloïse (France) — jeune"),
    ("fr-CA-SylvieNeural", "Sylvie (Québec)"),
    ("fr-BE-CharlineNeural", "Charline (Belgique)"),
    ("fr-CH-ArianeNeural", "Ariane (Suisse)"),
    ("fr-FR-HenriNeural", "Henri (France) — voix d'homme"),
)
OPENAI_VOICES = (
    ("coral", "Coral — chaleureuse"),
    ("nova", "Nova — jeune et vive"),
    ("shimmer", "Shimmer — douce"),
    ("sage", "Sage — calme"),
    ("marin", "Marin — naturelle"),
    ("ballad", "Ballad — expressive"),
    ("alloy", "Alloy — neutre"),
    ("verse", "Verse — dynamique"),
    ("cedar", "Cedar — voix grave"),
)
SENSITIVITY = {
    1: "Peu sensible (pièce bruyante, casque ouvert)",
    2: "Plutôt peu sensible",
    3: "Normale",
    4: "Sensible",
    5: "Très sensible (micro éloigné, voix basse)",
}


def rate_percent(rate: str) -> int:
    """« +8% » → 8."""
    match = re.fullmatch(r"\s*([+-]?\d+)\s*%\s*", rate or "")
    return int(match.group(1)) if match else 0


def _title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


def _panel() -> tuple[QFrame, QGridLayout]:
    frame = QFrame()
    frame.setObjectName("panel")
    grid = QGridLayout(frame)
    grid.setContentsMargins(18, 14, 18, 16)
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(10)
    grid.setColumnStretch(1, 1)
    return frame, grid


class SettingsPage(QScrollArea):
    setting_changed = Signal(str, object)  # (réglage, valeur)
    test_mic = Signal()
    test_voice = Signal()
    open_ai = Signal()

    def __init__(
        self,
        shortcuts: ShortcutsPage,
        input_devices: Callable[[], list[str]] | None = None,
        output_devices: Callable[[], list[str]] | None = None,
    ) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        self._input_devices = input_devices or (lambda: [])
        self._output_devices = output_devices or (lambda: [])
        self._loading = False
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)
        title = QLabel("RÉGLAGES")
        title.setFont(title_font(16))
        title.setStyleSheet(f"color:{PINK};")
        layout.addWidget(title)

        # --- Vision ------------------------------------------------------------------------------
        vision, grid = _panel()
        grid.addWidget(_title("VISION"), 0, 0, 1, 3)
        self.vision_box = QComboBox()
        self.vision_box.addItem("L'application (le jeu au premier plan)", "window")
        self.vision_box.addItem("Autour du curseur de la souris", "cursor")
        self.vision_box.addItem("L'écran entier", "screen")
        grid.addWidget(QLabel("ALICIA regarde"), 1, 0)
        grid.addWidget(self.vision_box, 1, 1, 1, 2)
        self.box_size = QComboBox()
        for size, label in (
            ("800x500", "Petite (800 × 500)"),
            ("1280x800", "Moyenne (1280 × 800)"),
            ("1920x1080", "Grande (1920 × 1080)"),
        ):
            self.box_size.addItem(label, size)
        grid.addWidget(QLabel("Zone du curseur"), 2, 0)
        grid.addWidget(self.box_size, 2, 1, 1, 2)
        self.live_box = QCheckBox(
            "Vision en direct : l'écran du moment où tu parles est déjà prêt (pas besoin de F9)"
        )
        self.live_interval = QComboBox()
        for seconds, label in (
            (5.0, "Quand tu parles + toutes les 5 s"),
            (10.0, "Quand tu parles + toutes les 10 s"),
            (30.0, "Quand tu parles + toutes les 30 s"),
        ):
            self.live_interval.addItem(label, seconds)
        grid.addWidget(self.live_box, 4, 0, 1, 2)
        grid.addWidget(self.live_interval, 4, 2)
        grid.addWidget(
            _muted(
                "Les images restent en mémoire sur ton PC : rien n'est envoyé à l'IA tant que tu "
                "ne lui parles pas."
            ),
            5,
            0,
            1,
            3,
        )
        grid.addWidget(
            _muted(
                "Autour du curseur : pointe un objet, un sort ou un texte avec la souris et "
                "demande « c'est quoi ça ? » ; un cercle rose montre à l'IA ce que tu désignes. "
                "Écran entier : utile avec plusieurs fenêtres (guide, carte, chat)."
            ),
            3,
            0,
            1,
            3,
        )
        layout.addWidget(vision)

        # --- Mémoire de partie ---------------------------------------------------------------
        memory, grid = _panel()
        grid.addWidget(_title("MÉMOIRE DE PARTIE"), 0, 0, 1, 3)
        self.memory_box = QCheckBox(
            "Garder de petites captures datées pour « il y a une heure… », « tout à l'heure… »"
        )
        grid.addWidget(self.memory_box, 1, 0, 1, 3)
        self.memory_interval = QComboBox()
        for seconds, label in (
            (15.0, "Toutes les 15 s"),
            (30.0, "Toutes les 30 s"),
            (60.0, "Toutes les minutes"),
        ):
            self.memory_interval.addItem(label, seconds)
        self.memory_hours = QComboBox()
        for hours, label in (
            (2.0, "2 heures"),
            (8.0, "8 heures"),
            (20.0, "20 heures"),
            (48.0, "2 jours"),
            (168.0, "7 jours"),
            (720.0, "30 jours"),
        ):
            self.memory_hours.addItem(label, hours)
        self.memory_size = QComboBox()
        for size, label in (
            (2.0, "2 Go"),
            (5.0, "5 Go"),
            (20.0, "20 Go"),
            (100.0, "100 Go"),
            (500.0, "500 Go"),
        ):
            self.memory_size.addItem(label, size)
        pick = QPushButton("Choisir un disque / dossier…")
        pick.clicked.connect(lambda: self.setting_changed.emit("memory_folder_pick", True))
        default_folder = QPushButton("Dossier par défaut")
        default_folder.setObjectName("ghost")
        default_folder.clicked.connect(lambda: self.setting_changed.emit("memory_folder", ""))
        grid.addWidget(QLabel("Une image"), 2, 0)
        grid.addWidget(self.memory_interval, 2, 1, 1, 2)
        grid.addWidget(QLabel("Gardées pendant"), 3, 0)
        grid.addWidget(self.memory_hours, 3, 1, 1, 2)
        self.memory_clear_exit = QCheckBox("Tout effacer à la fermeture d'ALICIA")
        grid.addWidget(QLabel("Place maximale"), 4, 0)
        grid.addWidget(self.memory_size, 4, 1, 1, 2)
        grid.addWidget(QLabel("Emplacement"), 5, 0)
        grid.addWidget(pick, 5, 1)
        grid.addWidget(default_folder, 5, 2)
        grid.addWidget(self.memory_clear_exit, 7, 0, 1, 3)
        self.memory_usage = _muted("")
        clear_now = QPushButton("Effacer maintenant")
        clear_now.clicked.connect(lambda: self.setting_changed.emit("memory_clear", True))
        grid.addWidget(self.memory_usage, 8, 0, 1, 2)
        grid.addWidget(clear_now, 8, 2)
        grid.addWidget(
            _muted(
                "Images réduites (environ 100 Ko), sur ton PC seulement, prises pendant la vision "
                "en direct. Nettoyage automatique au lancement et toutes les heures, et jamais "
                "plus de 10 000 images. Elles ne partent à l'IA que si ta question parle du passé. "
                "Avec un disque dédié, choisis-le dans « Emplacement » et monte la durée et la place."
            ),
            9,
            0,
            1,
            3,
        )
        layout.addWidget(memory)

        # --- Micro -------------------------------------------------------------------------------
        mic, grid = _panel()
        grid.addWidget(_title("MICRO"), 0, 0, 1, 3)
        self.input_box = QComboBox()
        grid.addWidget(QLabel("Micro"), 1, 0)
        grid.addWidget(self.input_box, 1, 1, 1, 2)
        self.mic_level = QProgressBar()
        self.mic_level.setRange(0, 100)
        self.mic_level.setTextVisible(False)
        self.mic_level.setFixedHeight(10)
        self.mic_test = QPushButton("Tester le micro (3 s)")
        self.mic_test.clicked.connect(self.test_mic.emit)
        grid.addWidget(self.mic_test, 2, 0)
        grid.addWidget(self.mic_level, 2, 1, 1, 2)
        self.mic_result = _muted("Parle pendant le test : ALICIA te dit ce qu'elle a compris.")
        grid.addWidget(self.mic_result, 3, 0, 1, 3)
        self.wake_box = QCheckBox("Réveil vocal : commencer sa phrase par « Alicia »")
        grid.addWidget(self.wake_box, 4, 0, 1, 3)
        self.sensitivity = QSlider(Qt.Orientation.Horizontal)
        self.sensitivity.setRange(1, 5)
        self.sensitivity.setPageStep(1)
        self.sensitivity.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.sensitivity_label = _muted("")
        grid.addWidget(QLabel("Sensibilité"), 5, 0)
        grid.addWidget(self.sensitivity, 5, 1)
        grid.addWidget(self.sensitivity_label, 5, 2)
        grid.addWidget(
            _muted(
                "Si ALICIA se réveille toute seule (jeu, amis en vocal), baisse la sensibilité ; "
                "si elle ne t'entend pas dire « Alicia », monte-la."
            ),
            6,
            0,
            1,
            3,
        )
        layout.addWidget(mic)

        # --- Voix --------------------------------------------------------------------------------
        voice, grid = _panel()
        grid.addWidget(_title("VOIX D'ALICIA"), 0, 0, 1, 3)
        self.speak_box = QCheckBox("Lire les réponses à voix haute")
        grid.addWidget(self.speak_box, 1, 0, 1, 3)
        self.engine_box = QComboBox()
        self.engine_box.addItem("Edge — voix Microsoft en ligne (plus naturelle)", "edge")
        self.engine_box.addItem("Kokoro — voix sur ton PC (hors ligne)", "kokoro")
        self.engine_box.addItem("OpenAI — voix très réaliste (clé OpenAI, payant)", "openai")
        self.engine_box.addItem("VERIS — voix robot de VERIS MOD (sur ton PC)", "veris")
        grid.addWidget(QLabel("Moteur"), 2, 0)
        grid.addWidget(self.engine_box, 2, 1, 1, 2)
        self.voice_box = QComboBox()
        for name, label in EDGE_VOICES:
            self.voice_box.addItem(label, name)
        self.voice_label = QLabel("Voix")
        grid.addWidget(self.voice_label, 3, 0)
        grid.addWidget(self.voice_box, 3, 1, 1, 2)
        self.openai_voice_box = QComboBox()
        for name, label in OPENAI_VOICES:
            self.openai_voice_box.addItem(label, name)
        grid.addWidget(self.openai_voice_box, 3, 1, 1, 2)
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(-20, 40)
        self.speed.setSingleStep(2)
        self.speed_label = _muted("")
        grid.addWidget(QLabel("Vitesse"), 4, 0)
        grid.addWidget(self.speed, 4, 1)
        grid.addWidget(self.speed_label, 4, 2)
        self.output_box = QComboBox()
        grid.addWidget(QLabel("Sortie"), 5, 0)
        grid.addWidget(self.output_box, 5, 1, 1, 2)
        self.voice_test = QPushButton("Tester la voix")
        self.voice_test.clicked.connect(self.test_voice.emit)
        grid.addWidget(self.voice_test, 6, 0)
        layout.addWidget(voice)

        # --- Général -------------------------------------------------------------------------------
        general, grid = _panel()
        grid.addWidget(_title("GÉNÉRAL"), 0, 0, 1, 3)
        self.ai_label = QLabel("")
        change_ai = QPushButton("Changer d'IA / de clé")
        change_ai.clicked.connect(self.open_ai.emit)
        grid.addWidget(QLabel("IA"), 1, 0)
        grid.addWidget(self.ai_label, 1, 1)
        grid.addWidget(change_ai, 1, 2)
        self.mode_box = QComboBox()
        self.mode_box.addItem("Seulement le rond d'ALICIA (mode bulle)", "orb")
        self.mode_box.addItem("Le panneau complet", "full")
        grid.addWidget(QLabel("Au lancement"), 2, 0)
        grid.addWidget(self.mode_box, 2, 1, 1, 2)
        self.persona_box = QComboBox()
        for persona in PERSONAS.values():
            self.persona_box.addItem(persona.title, persona.key)
        self.persona_box.setCurrentIndex(max(0, self.persona_box.findData(current_persona().key)))
        self.persona_box.currentIndexChanged.connect(
            lambda _i: self._emit("persona", self.persona_box.currentData())
        )
        grid.addWidget(QLabel("Personnage"), 3, 0)
        grid.addWidget(self.persona_box, 3, 1)
        grid.addWidget(_muted("nom, portrait, couleurs, voix (redémarrage)"), 3, 2)
        self.stream_box = QCheckBox(
            "Visible en stream : OBS / Discord montrent le rond et la bulle"
        )
        self.stream_box.toggled.connect(lambda on: self._emit("stream_visible", on))
        grid.addWidget(self.stream_box, 4, 0, 1, 3)
        grid.addWidget(
            _muted(
                "Coupé : ils sont invisibles pour les captures. Activé en vision « écran entier » "
                "ou « curseur », l'IA peut aussi les voir sur l'image."
            ),
            5,
            0,
            1,
            3,
        )
        layout.addWidget(general)

        # --- Raccourcis (onglet précédent, intégré ici) --------------------------------------
        self.shortcuts = shortcuts
        layout.addWidget(shortcuts)
        layout.addStretch(1)
        self.setWidget(host)

        # Signaux (ignorés pendant le chargement des valeurs)
        self.input_box.currentIndexChanged.connect(
            lambda _i: self._emit("input_device", self.input_box.currentData())
        )
        self.wake_box.toggled.connect(lambda on: self._emit("wake_word", on))
        self.sensitivity.valueChanged.connect(self._sensitivity_changed)
        self.speak_box.toggled.connect(lambda on: self._emit("speak_answers", on))
        self.engine_box.currentIndexChanged.connect(self._engine_changed)
        self.voice_box.currentIndexChanged.connect(
            lambda _i: self._emit("tts_voice", self.voice_box.currentData())
        )
        self.openai_voice_box.currentIndexChanged.connect(
            lambda _i: self._emit("openai_voice", self.openai_voice_box.currentData())
        )
        self.speed.valueChanged.connect(lambda v: self.speed_label.setText(f"{v:+d} %"))
        self.speed.sliderReleased.connect(lambda: self._emit("speed", self.speed.value()))
        self.output_box.currentIndexChanged.connect(
            lambda _i: self._emit("output_device", self.output_box.currentData())
        )
        self.vision_box.currentIndexChanged.connect(
            lambda _i: self._emit("vision", self.vision_box.currentData())
        )
        self.box_size.currentIndexChanged.connect(
            lambda _i: self._emit("cursor_box", self.box_size.currentData())
        )
        self.live_box.toggled.connect(lambda on: self._emit("live", on))
        self.memory_box.toggled.connect(lambda on: self._emit("memory", on))
        self.memory_interval.currentIndexChanged.connect(
            lambda _i: self._emit("memory_interval_s", self.memory_interval.currentData())
        )
        self.memory_hours.currentIndexChanged.connect(
            lambda _i: self._emit("memory_hours", self.memory_hours.currentData())
        )
        self.memory_clear_exit.toggled.connect(lambda on: self._emit("memory_clear_on_exit", on))
        self.memory_size.currentIndexChanged.connect(
            lambda _i: self._emit("memory_max_gb", self.memory_size.currentData())
        )
        self.live_interval.currentIndexChanged.connect(
            lambda _i: self._emit("live_interval_s", self.live_interval.currentData())
        )
        self.mode_box.currentIndexChanged.connect(
            lambda _i: self._emit("ui_mode", self.mode_box.currentData())
        )

    # --- valeurs --------------------------------------------------------------------------------

    def _emit(self, key: str, value: object) -> None:
        if not self._loading:
            self.setting_changed.emit(key, value)

    def _sensitivity_changed(self, value: int) -> None:
        self.sensitivity_label.setText(SENSITIVITY.get(value, ""))
        self._emit("wake_sensitivity", value)

    def _show_voice_list(self, engine: str) -> None:
        self.voice_box.setVisible(engine == "edge")
        self.openai_voice_box.setVisible(engine == "openai")
        self.voice_label.setVisible(engine in ("edge", "openai"))

    def _engine_changed(self) -> None:
        self._show_voice_list(self.engine_box.currentData())
        self._emit("tts_engine", self.engine_box.currentData())

    @staticmethod
    def _fill_devices(box: QComboBox, names: list[str], current: str, default: str) -> None:
        box.clear()
        box.addItem(default, "")
        for name in names:
            box.addItem(name, name)
        if current and box.findData(current) < 0:
            box.addItem(f"{current} (introuvable)", current)
        box.setCurrentIndex(max(0, box.findData(current)))

    def load(self, voice: VoiceSettings, wake_on: bool, ui_mode: str, ai_text: str) -> None:
        """Affiche les réglages actuels (sans rien déclencher)."""
        self._loading = True
        try:
            try:
                inputs, outputs = self._input_devices(), self._output_devices()
            except Exception:  # noqa: BLE001 - pas de carte son : menus réduits au défaut
                inputs, outputs = [], []
            self._fill_devices(
                self.input_box, inputs, voice.input_device, "Micro Windows par défaut"
            )
            self._fill_devices(
                self.output_box, outputs, voice.output_device, "Sortie Windows par défaut"
            )
            self.wake_box.setChecked(wake_on)
            self.sensitivity.setValue(voice.wake_sensitivity)
            self.sensitivity_label.setText(SENSITIVITY.get(voice.wake_sensitivity, ""))
            self.speak_box.setChecked(voice.speak_answers)
            self.engine_box.setCurrentIndex(max(0, self.engine_box.findData(voice.tts_engine)))
            self._show_voice_list(voice.tts_engine)
            if self.openai_voice_box.findData(voice.openai_voice) < 0:
                self.openai_voice_box.addItem(voice.openai_voice, voice.openai_voice)
            self.openai_voice_box.setCurrentIndex(
                self.openai_voice_box.findData(voice.openai_voice)
            )
            if self.voice_box.findData(voice.tts_voice) < 0:
                self.voice_box.addItem(voice.tts_voice, voice.tts_voice)
            self.voice_box.setCurrentIndex(self.voice_box.findData(voice.tts_voice))
            percent = rate_percent(voice.tts_rate)
            self.speed.setValue(percent)
            self.speed_label.setText(f"{percent:+d} %")
            self.mode_box.setCurrentIndex(max(0, self.mode_box.findData(ui_mode)))
            self.ai_label.setText(ai_text)
        finally:
            self._loading = False

    def load_memory(self, capture, usage: str) -> None:  # type: ignore[no-untyped-def]
        self._loading = True
        try:
            self.memory_box.setChecked(capture.memory)
            for box, value, unit in (
                (self.memory_interval, capture.memory_interval_s, "s"),
                (self.memory_size, capture.memory_max_gb, "Go"),
                (self.memory_hours, capture.memory_hours, "h"),
            ):
                if box.findData(value) < 0:
                    box.addItem(f"{value:g} {unit}", value)
                box.setCurrentIndex(box.findData(value))
            self.memory_clear_exit.setChecked(capture.memory_clear_on_exit)
            self.memory_usage.setText(usage)
        finally:
            self._loading = False

    def load_vision(
        self, mode: str, box: tuple[int, int], live: bool = True, interval: float = 1.0
    ) -> None:
        self._loading = True
        try:
            self.live_box.setChecked(live)
            index = self.live_interval.findData(interval)
            if index < 0:
                self.live_interval.addItem(f"Toutes les {interval:g} s", interval)
                index = self.live_interval.findData(interval)
            self.live_interval.setCurrentIndex(index)
            self.vision_box.setCurrentIndex(max(0, self.vision_box.findData(mode)))
            key = f"{box[0]}x{box[1]}"
            if self.box_size.findData(key) < 0:
                self.box_size.addItem(f"Personnalisée ({box[0]} × {box[1]})", key)
            self.box_size.setCurrentIndex(self.box_size.findData(key))
        finally:
            self._loading = False

    def show_mic_level(self, level: float) -> None:
        self.mic_level.setValue(int(max(0.0, min(1.0, level)) * 100))
