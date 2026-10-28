import logging
import time
from dataclasses import replace
from html import escape

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QCloseEvent, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from alicia.audio.formatting import spoken_excerpt
from alicia.audio.ports import SpeechError
from alicia.config import Settings
from alicia.core.models import AnalysisRequest
from alicia.core.ports import AnalysisError, CaptureError, ConfigurationError
from alicia.core.session import Session
from alicia.providers import create_speech_provider
from alicia.research.search import DuckDuckGoSearch, SearchError
from alicia.ui.avatar import Avatar
from alicia.ui.conversation import ConversationController
from alicia.ui.playback import SpeechPlayback
from alicia.ui.preview import CapturePreview
from alicia.ui.workers import Worker

logger = logging.getLogger("alicia.ui")

STYLE = """
QWidget { background: #101823; color: #e8edf5; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
QMainWindow { background: #101823; }
QFrame#card { background: #182433; border: 1px solid #2a394b; border-radius: 16px; }
QFrame#card QLabel, QFrame#card QWidget { background: transparent; }
QLabel#title { font-size: 30px; font-weight: 700; }
QLabel#muted { color: #aab9cc; }
QLabel#state { color: #9aead6; font-weight: 600; }
QPushButton { background: #293a50; border: 1px solid #3c506a; border-radius: 8px; padding: 10px 14px; }
QPushButton:hover { background: #354e69; }
QPushButton:disabled { color: #62748b; background: #1b293a; border-color: #28394e; }
QPushButton#primary { background: #9aead6; color: #102c2e; font-weight: 700; }
QPushButton#primary:disabled { background: #355d59; color: #8aa4a0; }
QPlainTextEdit, QComboBox { background: #101b29; border: 1px solid #3a4c64; border-radius: 8px; padding: 9px; selection-background-color: #375c69; }
QCheckBox { spacing: 8px; }
QSplitter::handle { background: #29394d; }
"""


def label(text, name=None):
    widget = QLabel(text)
    widget.setWordWrap(True)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, action, primary=False):
    widget = QPushButton(text)
    if primary:
        widget.setObjectName("primary")
    widget.clicked.connect(action)
    return widget


class MainWindow(QMainWindow):
    def __init__(
        self, settings: Settings, capture_source, vision_provider, demo=False, autostart=False
    ):
        super().__init__()
        self.settings = settings
        self.capture_source = capture_source
        self.vision_provider = vision_provider
        self.speech_provider = create_speech_provider(settings)
        self.research_provider = DuckDuckGoSearch()
        self.session = Session()
        self.pool = QThreadPool.globalInstance()
        self.jobs = set()
        self.workers = {}
        self.audio_generation = 0
        self.close_pending = False
        self.automatic_mode = autostart and not demo
        self.autostart_pending = False
        self.startup_timer = QTimer(self)
        self.startup_timer.setSingleShot(True)
        self.startup_timer.timeout.connect(self._begin_automatic)
        self.background_capture_active = False
        self.conversation = ConversationController(self)
        self.playback = SpeechPlayback(self)
        self.playback.speaking_changed.connect(self._speaking)
        self.playback.failed.connect(self._error)
        self.playback.finished.connect(self._audio_finished)
        self.setWindowTitle("Alicia — Votre copilote de jeu")
        self.resize(1240, 1020)
        self.setMinimumSize(1000, 900)
        self.setStyleSheet(STYLE)
        self._build_ui(demo)
        self.refresh_windows()
        self.autostart_pending = self.automatic_mode

    def _build_ui(self, demo):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(16)
        header = QHBoxLayout()
        header.addWidget(label("ALICIA", "title"))
        header.addStretch()
        header.addWidget(label("V0.4  ·  Copilote visuel & vocal", "muted"))
        layout.addLayout(header)
        layout.addWidget(
            label(
                "MODE LOCAL GRATUIT · Aucune clé API ni abonnement"
                if self.settings.ai_provider == "ollama"
                and self.settings.tts_provider in {"windows", "kokoro", "chatterbox"}
                else "FOURNISSEUR EXTERNE ACTIVÉ · Des appels peuvent être facturés",
                "state",
            )
        )
        layout.addWidget(
            label(
                "DÉMONSTRATION — inventaire fictif, aucune fenêtre de jeu observée."
                if demo
                else "Votre partie, votre contrôle. Alicia observe votre écran et vous conseille.",
                "muted",
            )
        )
        body = QHBoxLayout()
        body.setSpacing(20)
        companion = QFrame()
        companion.setObjectName("card")
        companion.setFixedWidth(270)
        left = QVBoxLayout(companion)
        left.setContentsMargins(18, 20, 18, 20)
        left.addWidget(label("Votre copilote", "muted"))
        self.avatar = Avatar()
        left.addWidget(self.avatar)
        left.addWidget(label("Alicia", "title"))
        left.addWidget(label("Une présence calme à vos côtés.", "muted"))
        self.state_label = label("Prête à vous accompagner", "state")
        left.addWidget(self.state_label)
        left.addWidget(button("Choisir une image…", self.choose_avatar))
        left.addStretch()
        left.addWidget(label("VOIX IA · DOUCE & FÉMININE", "muted"))
        left.addWidget(
            label(
                "Voix synthétique sur votre PC. Lecture gratuite à la demande."
                if self.settings.tts_provider in {"windows", "kokoro", "chatterbox"}
                else "Lecture à la demande. La voix est générée par une IA.",
                "muted",
            )
        )
        self.speak_button = button("Lire la réponse", self.speak)
        left.addWidget(self.speak_button)
        self.mute_button = button("Arrêter la voix", self.stop_audio)
        left.addWidget(self.mute_button)
        left.addWidget(
            label("Dites « Alicia, stop » pour interrompre la voix. Casque conseillé.", "muted")
        )
        left.addWidget(label("Volume", "muted"))
        volume = QSlider(Qt.Horizontal)
        volume.setRange(0, 100)
        volume.setValue(55)
        volume.valueChanged.connect(self.playback.set_volume)
        left.addWidget(volume)
        left.addWidget(
            label(
                "Écoute locale au lancement. Stop coupe l’écran et le micro. Aucun contrôle du jeu.",
                "muted",
            )
        )
        body.addWidget(companion)
        right_widget = QWidget()
        right = QVBoxLayout(right_widget)
        right.setContentsMargins(0, 0, 10, 0)
        right.setSpacing(6)
        selection = QHBoxLayout()
        self.source_label = label("Écran principal" if not demo else "Démonstration", "state")
        selection.addWidget(self.source_label)
        self.source_button = QPushButton("Choisir une autre source…")
        self.source_button.setCheckable(True)
        selection.addWidget(self.source_button)
        right.addLayout(selection)
        selection = QHBoxLayout()
        self.windows = QComboBox()
        self.windows.setMinimumWidth(250)
        self.windows.currentIndexChanged.connect(self._selection_changed)
        selection.addWidget(self.windows, 1)
        self.refresh_button = button("Actualiser", self.refresh_windows)
        selection.addWidget(self.refresh_button)
        right.addLayout(selection)
        self.windows.setVisible(False)
        self.refresh_button.setVisible(False)
        self.source_button.toggled.connect(self.windows.setVisible)
        self.source_button.toggled.connect(self.refresh_button.setVisible)
        controls = QHBoxLayout()
        self.start_button = button(
            "Reprendre" if self.automatic_mode else "Démarrer", self.start, True
        )
        self.stop_button = button("Stop", self.stop)
        self.capture_button = button("Capturer", self.capture)
        for widget in (self.start_button, self.stop_button, self.capture_button):
            controls.addWidget(widget)
        right.addLayout(controls)
        self.conversation.build_controls(right)
        self.preview = CapturePreview("Sélectionnez une fenêtre, puis démarrez et capturez.")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(170)
        self.preview.setStyleSheet(
            "background: #0b131e; border: 1px solid #2a394b; border-radius: 12px;"
        )
        right.addWidget(self.preview, 3)
        self.capture_details = label("Aucune capture en mémoire.", "muted")
        right.addWidget(self.capture_details)
        self.question = QPlainTextEdit()
        self.question.setPlaceholderText("Que souhaitez-vous savoir sur cet écran ?")
        self.question.setMaximumHeight(85)
        self.question.textChanged.connect(self._update_controls)
        right.addWidget(self.question)
        self.consent = QCheckBox(
            "Autoriser l’analyse locale des captures manuelles et vocales."
            if self.settings.ai_provider == "ollama"
            else "J’autorise l’envoi de cette capture et de ma question au fournisseur IA."
        )
        self.consent.toggled.connect(self._update_controls)
        self.consent.toggled.connect(self.conversation.permission_changed)
        right.addWidget(self.consent)
        self.analyze_button = button("Analyser la capture", self.analyze, True)
        right.addWidget(self.analyze_button)
        right.addWidget(label("LA RÉPONSE D’ALICIA", "muted"))
        self.answer = QPlainTextEdit()
        self.answer.setReadOnly(True)
        self.answer.setPlaceholderText(
            "La réponse apparaîtra ici. Alicia peut signaler une information illisible ou incertaine."
        )
        right.addWidget(self.answer, 2)
        self.sources = QTextBrowser()
        self.sources.setOpenExternalLinks(True)
        self.sources.setMaximumHeight(100)
        self.sources.hide()
        right.addWidget(self.sources)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(right_widget)
        body.addWidget(scroll, 1)
        layout.addLayout(body, 1)
        self.events = QPlainTextEdit()
        self.events.setReadOnly(True)
        self.events.setMaximumBlockCount(150)
        self.events.setFixedHeight(90)
        layout.addWidget(self.events)
        self._event(
            "Écran principal et écoute locale au lancement. Stop coupe l’observation et le micro."
            if self.automatic_mode
            else "Mode manuel : aucun microphone activé automatiquement."
        )
        if self.settings.ai_provider == "ollama":
            self._event("Mode gratuit local : Ollama pour les images, aucune clé API nécessaire.")
        elif not self.settings.api_key:
            self._event(
                "Clé API absente : capture disponible, analyse et voix à configurer dans .env."
            )
        if self.settings.tts_provider == "windows":
            self._event("Voix française féminine Windows : synthèse locale gratuite.")
        elif self.settings.tts_provider == "kokoro":
            self._event("Voix neuronale française Kokoro : synthèse locale gratuite.")
        elif self.settings.tts_provider == "chatterbox":
            self._event("Voix française expressive Chatterbox : synthèse locale gratuite.")
        self._update_controls()

    def _event(self, message):
        self.events.appendPlainText(time.strftime("%H:%M:%S") + "  " + message)
        logger.info("user_event message=%s", message)

    def _state(self, message, avatar="idle"):
        self.state_label.setText(message)
        self.avatar.set_state(avatar)

    def _error(self, message, *, stop_microphone=False):
        if self.automatic_mode and not stop_microphone and self.conversation.listener is not None:
            self.conversation._finish_question()
        else:
            self.conversation.stop_listening()
        if self.background_capture_active:
            self.conversation.continuous.setChecked(False)
        self._event(message)
        self._state("Une action demande votre attention", "error")

    def _job(self, kind, operation, callback):
        if kind in self.jobs:
            return
        self.jobs.add(kind)
        generation = self.session.generation
        audio_generation = self.audio_generation
        self.conversation.before_job(kind)
        worker = Worker(
            operation, (CaptureError, AnalysisError, ConfigurationError, SpeechError, SearchError)
        )
        worker.signals.setParent(self)
        self.workers[kind] = worker
        worker.signals.succeeded.connect(callback)
        worker.signals.failed.connect(
            lambda message: (
                self._error(message)
                if generation == self.session.generation
                and (kind != "speech" or audio_generation == self.audio_generation)
                else None
            )
        )
        worker.signals.finished.connect(lambda: self._finished(kind))
        self._update_controls()
        self.pool.start(worker)

    def _finished(self, kind):
        self.jobs.discard(kind)
        worker = self.workers.pop(kind, None)
        if worker is not None:
            worker.signals.deleteLater()
        if kind == "capture":
            self.background_capture_active = False
        self._update_controls()
        self.conversation.job_finished(kind)
        if kind == "windows" and self.autostart_pending and not self.close_pending:
            self.startup_timer.start(0)
        if self.close_pending and not self.jobs:
            QTimer.singleShot(0, self.close)

    def _update_controls(self):
        if not hasattr(self, "analyze_button"):
            return
        busy = bool(self.jobs)
        self.refresh_button.setEnabled(not busy)
        self.windows.setEnabled(not busy)
        self.start_button.setEnabled(
            not busy and not self.session.active and self.windows.currentData() is not None
        )
        self.stop_button.setEnabled(self.session.active)
        self.capture_button.setEnabled(self.session.active and not busy)
        self.analyze_button.setEnabled(
            self.session.active
            and self.session.frame is not None
            and bool(self.question.toPlainText().strip())
            and self.consent.isChecked()
            and not busy
        )
        self.speak_button.setEnabled(self.session.result is not None and not busy)
        self.conversation.refresh_controls()

    def refresh_windows(self):
        if self.jobs:
            return
        self.stop()
        self._job("windows", self.capture_source.list_windows, self._windows_loaded)

    def _windows_loaded(self, windows):
        self.windows.blockSignals(True)
        self.windows.clear()
        for window in windows:
            self.windows.addItem(window.title, window)
        self.windows.blockSignals(False)
        if windows:
            self.source_label.setText(windows[0].title)
        self._event(f"{len(windows)} fenêtre(s) disponible(s).")
        if not windows:
            self._event("Aucune fenêtre visible. Ouvrez un jeu en mode fenêtré puis actualisez.")

    def _selection_changed(self):
        self.stop()
        window = self.windows.currentData()
        if window is not None:
            self.source_label.setText(window.title)

    def _begin_automatic(self):
        if self.autostart_pending and not self.close_pending:
            self.autostart_pending = False
            self.start()

    def start(self):
        window = self.windows.currentData()
        if window is None or self.jobs:
            return
        self.session.start(window)
        logger.info("observation_started window_handle=%s", window.handle)
        self._state("Observation prête · vision locale")
        self._event(
            "Fenêtre sélectionnée. L’aperçu local s’actualise si la vision continue est cochée."
        )
        self.conversation.observation_changed()
        self._update_controls()
        if self.automatic_mode:
            self.consent.setChecked(True)
            if self.conversation.listener is None or not self.conversation.listener.active:
                self.conversation.toggle_listening()

    def stop(self):
        self.startup_timer.stop()
        self.autostart_pending = False
        self.conversation.stop_listening()
        self.conversation.timer.stop()
        self.session.stop()
        self.audio_generation += 1
        self.playback.stop()
        self._close_speech_provider()
        self.preview.clear()
        self.preview.setText("Observation arrêtée. Aucune capture active.")
        self.capture_details.setText("Aucune capture en mémoire.")
        self.answer.clear()
        self.sources.clear()
        self.sources.hide()
        self.consent.setChecked(False)
        self._state("Observation arrêtée")
        logger.info("observation_stopped")
        self._update_controls()

    def capture(self, vocal=False, *, background=False):
        if self.jobs or not self.session.active:
            return
        self.background_capture_active = background
        if not background:
            self.playback.stop()
            self.audio_generation += 1
            self.session.frame = None
            self.session.result = None
            self.answer.clear()
            self.sources.clear()
            self.sources.hide()
            self.preview.clear()
            self.preview.setText("Nouvelle capture en cours…")
            self.capture_details.setText("Aucune capture prête.")
            if not vocal and not self.automatic_mode:
                self.consent.setChecked(False)
        generation, window = self.session.generation, self.session.window
        if not background:
            self._state("Capture en cours…", "capturing")
        self._job(
            "capture",
            lambda: self.capture_source.capture(window),
            lambda frame: self._captured(generation, frame, vocal=vocal, background=background),
        )

    def _captured(self, generation, frame, *, vocal=False, background=False):
        previous_result = self.session.result
        if not self.session.accept_frame(generation, frame):
            return
        if background:
            self.session.result = previous_result
        image = QPixmap()
        image.loadFromData(frame.png, "PNG")
        self.preview.setPixmap(image)
        self.capture_details.setText(
            f"Capture {frame.width} × {frame.height} · {frame.captured_at.astimezone():%H:%M:%S}"
        )
        if not background:
            self.answer.clear()
            if not vocal and not self.automatic_mode:
                self.consent.setChecked(False)
            self._state("Capture prête à être analysée")
            self._event("Capture locale réussie. Aucune image envoyée.")
        log = logger.debug if background else logger.info
        log(
            "capture_completed capture_id=%s width=%s height=%s",
            frame.capture_id,
            frame.width,
            frame.height,
        )

    def analyze(self):
        if (
            self.jobs
            or not self.session.active
            or not self.session.frame
            or not self.consent.isChecked()
        ):
            return
        self.playback.stop()
        self.audio_generation += 1
        self.session.result = None
        self.answer.clear()
        self.sources.clear()
        self.sources.hide()
        generation = self.session.generation
        request = AnalysisRequest(
            self.session.frame, self.question.toPlainText(), history=self.session.memory.snapshot()
        )
        self._state("Je regarde votre capture…", "thinking")
        if self.conversation.web.isChecked():
            self._state("Je recherche des sources sur le web…", "thinking")
            self._event("Recherche web demandée : seule la question est envoyée au moteur.")
            self._job(
                "research",
                lambda: self.research_provider.search(request.question),
                lambda sources: self._researched(generation, request, sources),
            )
            return
        self._start_analysis(generation, request)

    def _researched(self, generation, request, sources):
        if (
            self.session.active
            and self.session.generation == generation
            and self.conversation.web.isChecked()
            and self.session.frame is not None
            and self.session.frame.capture_id == request.frame.capture_id
        ):
            self._event(
                f"{len(sources)} extraits de recherche reçus. Leur date de publication reste à vérifier."
            )
            self._start_analysis(generation, replace(request, web_sources=tuple(sources)))

    def _start_analysis(self, generation, request):
        self._state("Je regarde votre capture…", "thinking")
        self._event(
            "Analyse demandée : traitement local sur votre PC par Ollama."
            if self.settings.ai_provider == "ollama"
            else "Analyse demandée : envoi de la capture et de la question au fournisseur externe."
        )
        self._job(
            "analysis",
            lambda: self.vision_provider.analyze(request),
            lambda result: self._analyzed(generation, result, question=request.question),
        )

    def _analyzed(self, generation, result, *, question=None):
        if self.session.accept_result(generation, result):
            if question is not None:
                self.session.memory.append(question, result.text)
            self.answer.setPlainText(result.text)
            self._state("Voici ce que j’observe")
            self._event(
                f"Réponse reçue en {result.elapsed_seconds:.1f} s. Lecture vocale disponible à la demande."
            )
            if result.web_sources:
                items = [
                    f'<b>[{index}]</b> <a href="{escape(source.url, quote=True)}">{escape(source.title)}</a>'
                    f" — récupéré le {source.retrieved_at.astimezone():%d/%m/%Y à %H:%M}"
                    for index, source in enumerate(result.web_sources, 1)
                ]
                self.sources.setHtml(
                    "<b>Sources : extraits du moteur, pages non consultées.</b><br>"
                    + "<br>".join(items)
                )
                self.sources.show()

    def speak(self):
        if self.jobs or self.session.result is None:
            return
        self.playback.stop()
        generation = self.session.generation
        self.audio_generation += 1
        audio_generation = self.audio_generation
        text = spoken_excerpt(self.session.result.text)
        self.conversation.prepare_speech(text)
        self._state("Je prépare ma voix…", "thinking")
        self._event(
            "Lecture demandée : voix locale, aucun texte envoyé sur Internet."
            if self.settings.tts_provider in {"windows", "kokoro", "chatterbox"}
            else "Lecture demandée : le texte de la réponse est envoyé au service vocal IA."
        )
        self._job(
            "speech",
            lambda: self.speech_provider.synthesize(text),
            lambda audio: self._speech_ready(generation, audio_generation, audio),
        )

    def _speech_ready(self, generation, audio_generation, audio):
        if (
            self.session.active
            and self.session.generation == generation
            and audio_generation == self.audio_generation
        ):
            self.playback.play(audio)

    def _speaking(self, active):
        if active:
            self.conversation.audio_started()
            self._state("Alicia vous parle · voix synthétique", "speaking")
        elif self.avatar.state == "speaking":
            self._state("Prête pour votre prochaine question")

    def _audio_finished(self):
        self._event("Lecture audio terminée.")
        self.conversation.audio_finished()

    def stop_audio(self):
        # Invalide aussi une synthèse qui n’a pas encore répondu.
        self.audio_generation += 1
        self.playback.stop()
        if "speech" in self.jobs:
            self._close_speech_provider()
        self.conversation.audio_finished()
        self._state("Voix arrêtée")
        self._event("Arrêt vocal demandé.")

    def _close_speech_provider(self):
        close_speech = getattr(self.speech_provider, "close", None)
        if close_speech is not None:
            close_speech()

    def cancel_pending_analysis(self):
        self.session.generation += 1
        self.session.result = None
        self.audio_generation += 1
        self.playback.stop()
        self._close_speech_provider()
        self.conversation.stop_listening()
        self.answer.clear()
        self.sources.clear()
        self.sources.hide()
        self._state("Résultat en cours ignoré après retrait de l’autorisation")
        self._event("Autorisation retirée : aucun résultat en attente ne sera utilisé.")

    def choose_avatar(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Image d’Alicia", "", "Images (*.png *.jpg *.jpeg *.webp)"
        )
        if path and not self.avatar.load_picture(path):
            self._error("Cette image ne peut pas être ouverte.")

    def closeEvent(self, event: QCloseEvent):
        self.stop()
        if self.jobs:
            self.close_pending = True
            self.centralWidget().setEnabled(False)
            self._event(
                "Fermeture demandée. L’opération en cours se termine avant de libérer ses ressources."
            )
            event.ignore()
            return
        logger.info("application_closed")
        self._close_speech_provider()
        event.accept()
