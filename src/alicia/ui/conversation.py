"""Coordonne écoute, réveil, capture fraîche et réponse sans bloquer Qt."""

import math
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QProgressBar, QPushButton

from alicia.audio.listening import list_input_devices
from alicia.audio.ports import SpeechError
from alicia.core.interruption import is_stop_command, speech_contains_stop_command
from alicia.core.wake_word import WakeWordGate
from alicia.providers import create_listener_factory


class ConversationController(QObject):
    final_received = Signal(int, int, str)
    partial_received = Signal(int, int, str)
    failed = Signal(int, str)
    activity_changed = Signal(int, bool)
    diagnostic_received = Signal(int, str)
    level_received = Signal(int, float)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.listener = None
        self.listener_factory = create_listener_factory(window.settings)
        self.serial = 0
        self.input_epoch = 0
        self.gate = WakeWordGate()
        self.phase = "idle"
        self.question = None
        self.generation = None
        self.vocal_request = True
        self.resume_not_before = 0.0
        self.interrupting = False
        self.speech_can_be_interrupted = False
        self.ready_serial = None
        self.cooldown_timer = QTimer(self)
        self.cooldown_timer.setSingleShot(True)
        self.cooldown_timer.setTimerType(Qt.PreciseTimer)
        self.cooldown_timer.timeout.connect(self.resume_if_idle)
        self.final_received.connect(self._heard)
        self.partial_received.connect(self._partial)
        self.failed.connect(self._failed)
        self.activity_changed.connect(self._activity)
        self.diagnostic_received.connect(self._diagnostic)
        self.level_received.connect(self._level)
        self.timer = QTimer(self)
        self.timer.setInterval(window.settings.capture_interval_ms)
        self.timer.timeout.connect(self._refresh_screen)

    def build_controls(self, layout):
        self.continuous = QCheckBox("Vision locale en continu")
        self.continuous.setChecked(True)
        self.continuous.toggled.connect(self.observation_changed)
        self.web = QCheckBox("Autoriser la recherche web avec ma question")
        self.web.setToolTip(
            "Seule votre question est envoyée au moteur de recherche, sans image ni audio."
        )
        self.web.toggled.connect(self._web_changed)
        row = QHBoxLayout()
        row.addWidget(self.continuous)
        row.addWidget(self.web)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.devices = QComboBox()
        self.devices.addItem("Microphone par défaut", None)
        self.device_refresh = QPushButton("Lister les micros")
        self.device_refresh.clicked.connect(self.refresh_devices)
        self.toggle = QPushButton("Activer le micro")
        self.toggle.clicked.connect(self.toggle_listening)
        self.toggle.setVisible(not self.window.automatic_mode)
        row.addWidget(self.devices, 1)
        row.addWidget(self.device_refresh)
        row.addWidget(self.toggle)
        layout.addLayout(row)
        self.auto_voice = QCheckBox("Réponse vocale automatique aux questions au micro")
        self.auto_voice.setChecked(True)
        layout.addWidget(self.auto_voice)
        self.status = QLabel(
            "Micro coupé · dites « Alicia » après activation pour poser une question."
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setValue(0)
        self.level.setFormat("Entrée du microphone")
        self.level.setMaximumHeight(18)
        self.level.setVisible(self.window.settings.stt_provider == "whisper")
        layout.addWidget(self.level)

    def refresh_controls(self):
        if not hasattr(self, "toggle"):
            return
        active = self.listener is not None and self.listener.active
        self.toggle.setText("Couper le micro" if active else "Activer le micro")
        self.toggle.setEnabled(
            active
            or (
                self.window.session.active
                and self.window.consent.isChecked()
                and not self.window.foreground_busy
            )
        )
        self.devices.setEnabled(not active and not self.window.foreground_busy)
        self.device_refresh.setEnabled(not active and not self.window.foreground_busy)

    def observation_changed(self):
        if self.window.session.active and self.continuous.isChecked():
            self.timer.start()
        else:
            self.timer.stop()

    def _refresh_screen(self):
        if (
            self.window.session.active
            and not self.window.jobs
            and self.phase == "idle"
            and not self.window.close_pending
        ):
            self.window.capture(background=True)

    def refresh_devices(self):
        if self.window.queue_after_preview("devices"):
            return
        if not self.window.jobs:
            self.window._job("devices", list_input_devices, self._devices_ready)

    def _devices_ready(self, devices):
        self.devices.clear()
        self.devices.addItem("Microphone par défaut", None)
        for index, name in devices:
            self.devices.addItem(name, index)

    def toggle_listening(self):
        if self.listener is not None and self.listener.active:
            self.stop_listening()
            return
        if self.window.queue_after_preview("listen"):
            return
        if (
            not self.window.session.active
            or not self.window.consent.isChecked()
            or self.window.jobs
        ):
            return
        if (
            self.window.settings.ai_provider != "ollama"
            or self.window.settings.tts_provider not in {"windows", "kokoro", "chatterbox"}
        ):
            self.window._error("Le mode mains libres gratuit requiert l’IA et la voix locales.")
            return
        self.serial += 1
        serial = self.serial
        self.status.setText("Initialisation du micro et du modèle de reconnaissance…")
        self.window._event(
            "Initialisation de l’écoute locale demandée. Aucun audio envoyé sur Internet."
        )
        try:
            self.listener = self.listener_factory(
                self.window.settings.whisper_model_path
                if self.window.settings.stt_provider == "whisper"
                else self.window.settings.voice_model_path,
                on_text=lambda text: self.final_received.emit(serial, self.input_epoch, text),
                on_partial=lambda text: self.partial_received.emit(serial, self.input_epoch, text),
                on_error=lambda message: self.failed.emit(serial, message),
                on_activity=lambda active: self.activity_changed.emit(serial, active),
            )
            if hasattr(self.listener, "on_status"):
                self.listener.on_status = lambda status: self.diagnostic_received.emit(
                    serial, status
                )
            if hasattr(self.listener, "on_level"):
                self.listener.on_level = lambda level: self.level_received.emit(serial, level)
            self.listener.start(self.devices.currentData())
        except SpeechError as error:
            self.window._error(str(error), stop_microphone=True)
            self.status.setText("Micro indisponible · " + str(error))
            return
        self.refresh_controls()

    def stop_listening(self):
        actions = getattr(self.window, "actions", None)
        if actions is not None and actions.request is not None and actions.request.vocal:
            actions.cancel()
        self.cooldown_timer.stop()
        self.serial += 1
        self.input_epoch += 1
        listener, self.listener = self.listener, None
        if listener is not None:
            setter = getattr(listener, "set_interruption_mode", None)
            if setter is not None:
                setter(False)
            listener.stop()
        self.interrupting = False
        self.speech_can_be_interrupted = False
        self.gate.reset()
        self.phase = "idle"
        self.question = None
        self.generation = None
        if hasattr(self, "status"):
            self.status.setText("Micro coupé · aucune écoute en cours.")
            self.level.setValue(0)
            self.refresh_controls()

    def _valid(self, serial, epoch):
        return (
            serial == self.serial
            and epoch == self.input_epoch
            and self.listener is not None
            and self.listener.active
            and not self.listener.paused
            and self.window.session.active
            and self.window.consent.isChecked()
        )

    def _activity(self, serial, active):
        if serial != self.serial:
            return
        if active:
            self.status.setText("En attente de « Alicia » · reconnaissance française locale.")
            if self.ready_serial != serial:
                self.ready_serial = serial
                self.window._event("Microphone prêt · dites « Alicia » pour donner une consigne.")
        elif self.listener is not None and not self.listener.active:
            self.status.setText("Micro arrêté · utilisez Reprendre pour relancer l’écoute.")
            self.level.setValue(0)
        self.refresh_controls()

    def _diagnostic(self, serial, state):
        if serial != self.serial or self.listener is None:
            return
        messages = {
            "waiting_model": "Modèle occupé · attente du chargement précédent…",
            "loading_model": "Chargement du modèle de reconnaissance local…",
            "cuda_probe": "Vérification de la carte graphique pour la reconnaissance…",
            "opening_microphone": "Ouverture du microphone…",
            "ready": "En attente de « Alicia » · reconnaissance française locale.",
            "transcribing": "Parole détectée · reconnaissance de votre demande…",
            "unrecognized": "Parole peu claire · dites « Alicia » puis votre demande.",
        }
        if state in {"ready", "transcribing", "unrecognized"} and self.phase != "idle":
            return
        if state == "ready" and self.gate.armed:
            return
        if state in messages:
            self.status.setText(messages[state])

    def _level(self, serial, value):
        if serial == self.serial and self.listener is not None and math.isfinite(value):
            # A visual input indicator, not a stored waveform or a dB reading.
            self.level.setValue(round(max(0.0, min(1.0, value * 4)) * 100))

    def _partial(self, serial, epoch, text):
        if (
            not self.interrupting
            and self._valid(serial, epoch)
            and "alicia" in text.casefold().split()
        ):
            self.status.setText("Alicia détecté · terminez votre question…")

    def _heard(self, serial, epoch, text):
        if not self._valid(serial, epoch):
            return
        if self.interrupting:
            if self.window.playback.active and is_stop_command(text):
                self.window.stop_audio()
            return
        if self.phase != "idle":
            return
        if is_stop_command(text):
            self.window.stop_audio()
            return
        query = self.gate.feed(text)
        if query is None:
            if self.gate.armed:
                self.status.setText("Oui ? Posez votre question dans les 8 prochaines secondes.")
            return
        if self.window.jobs and not self.window.background_capture_active:
            return
        self.question = query
        self.generation = self.window.session.generation
        self.vocal_request = True
        self.window.question.setPlainText(query)
        self.phase = "waiting"
        self.pause()
        self.status.setText("Demande reconnue · je prépare la suite…")
        self._advance()

    def pause(self):
        self.input_epoch += 1
        self.level.setValue(0)
        if self.listener is not None:
            self.listener.pause()

    def prepare_speech(self, text):
        """Arm interruption only for speech that cannot quote its own command."""
        self.speech_can_be_interrupted = not speech_contains_stop_command(text)

    def audio_started(self):
        """Listen for the stop command on the existing stream during playback."""
        if self.interrupting or not self.window.playback.active:
            return
        if (
            self.listener is None
            or not self.listener.active
            or not self.window.session.active
            or not self.window.consent.isChecked()
        ):
            return
        if not self.speech_can_be_interrupted:
            self.pause()
            self.status.setText(
                "Lecture en cours · utilisez « Arrêter la voix » pendant cette explication."
            )
            return
        self.cooldown_timer.stop()
        self.phase = "speaking"
        self.gate.reset()
        self.input_epoch += 1
        setter = getattr(self.listener, "set_interruption_mode", None)
        if setter is not None:
            setter(True)
        self.interrupting = True
        self.listener.resume()
        self.status.setText("Alicia parle · dites « Alicia, stop » pour couper sa voix.")

    def before_job(self, kind):
        if kind != "devices" and not (kind == "capture" and self.window.background_capture_active):
            if self.interrupting:
                self.input_epoch += 1
                setter = getattr(self.listener, "set_interruption_mode", None)
                if setter is not None:
                    setter(False)
                self.interrupting = False
                self.phase = "idle"
                self.question = self.generation = None
                self.gate.reset()
            self.pause()

    def _advance(self):
        if self.window.jobs or self.phase != "waiting":
            return
        if not self._request_current():
            self._finish_question()
            return
        self.phase = "routing"
        if not self.window.dispatch_request(self.question, vocal=True):
            self._finish_question()

    def begin_answer(self, question, *, vocal):
        """Reuse fresh capture/analysis for spoken and typed screen questions."""
        self.question = question
        self.generation = self.window.session.generation
        self.vocal_request = vocal
        self.window.question.setPlainText(question)
        if not self._request_current():
            self._finish_question()
            return
        self.phase = "capturing"
        self.window.capture(vocal=True)

    def _request_current(self):
        return (
            self.window.session.active
            and self.generation == self.window.session.generation
            and self.window.consent.isChecked()
            and (not self.vocal_request or (self.listener is not None and self.listener.active))
        )

    def job_finished(self, kind):
        if self.window.jobs:
            return
        if self.phase == "waiting":
            self._advance()
        elif self.phase == "capturing" and kind == "capture":
            if self._request_current() and self.window.session.frame is not None:
                self.phase = "analyzing"
                self.window.question.setPlainText(self.question)
                self.window.analyze()
            else:
                self._finish_question()
        elif self.phase == "analyzing":
            if (
                self._request_current()
                and self.window.session.result is not None
                and self.vocal_request
                and self.auto_voice.isChecked()
            ):
                self.phase = "speaking"
                self.window.speak()
            else:
                self._finish_question()
        elif self.phase == "speaking" and kind == "speech" and not self.window.playback.active:
            self._finish_question()
        self.resume_if_idle()

    def audio_finished(self):
        self._finish_question()

    def _finish_question(self):
        self.input_epoch += 1
        if self.listener is not None:
            setter = getattr(self.listener, "set_interruption_mode", None)
            if setter is not None:
                setter(False)
            self.listener.pause()
        self.interrupting = False
        self.speech_can_be_interrupted = False
        self.phase = "idle"
        self.question = None
        self.generation = None
        self.gate.reset()
        self.resume_not_before = time.monotonic() + 0.35
        self.cooldown_timer.start(350)

    def resume_if_idle(self):
        remaining = self.resume_not_before - time.monotonic()
        if (
            self.listener is not None
            and self.listener.active
            and self.listener.paused
            and remaining > 0
        ):
            self.cooldown_timer.start(max(1, math.ceil(remaining * 1000)))
            self.refresh_controls()
            return
        if (
            self.listener is not None
            and self.listener.active
            and self.listener.paused
            and time.monotonic() >= self.resume_not_before
            and self.phase == "idle"
            and not self.window.jobs
            and not self.window.playback.active
            and self.window.session.active
            and self.window.consent.isChecked()
        ):
            self.input_epoch += 1
            self.listener.resume()
            self.status.setText("En attente de « Alicia » · reconnaissance française locale.")
        self.refresh_controls()

    def permission_changed(self):
        if not self.window.consent.isChecked():
            self.window.clear_pending_requests()
            self.window.actions.cancel()
            if {"research", "analysis"}.intersection(self.window.jobs):
                self.window.cancel_pending_analysis()
            else:
                self.stop_listening()
        self.refresh_controls()

    def _web_changed(self, allowed):
        if not allowed and self.window.actions.busy:
            self.window.actions.cancel()
            self._finish_question()
        if not allowed and "research" in self.window.jobs:
            self.window.cancel_pending_analysis()
        self.window._event(
            "Recherche web autorisée : votre question pourra être envoyée au moteur, sans image ni audio."
            if allowed
            else "Recherche web désactivée."
        )

    def _failed(self, serial, message):
        if serial == self.serial:
            self.window._error(message, stop_microphone=True)
            self.status.setText("Micro indisponible · " + message)
