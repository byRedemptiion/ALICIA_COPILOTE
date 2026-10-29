"""Transcription locale de la voix du joueur avec faster-whisper (CPU, sans PyTorch).

Réglages et filtre d'hallucinations repris de huburton/jarvis (MIT) : langue imposée,
beam_size=1 pour la vitesse, VAD intégrée, pas de conditionnement sur le texte précédent.
"""

from __future__ import annotations

import io
import logging
import os
import re
import threading
import time
import wave

import numpy as np

from alice.core.ai.base import PreparedAudio
from alice.core.audio.devices import AudioError

log = logging.getLogger("alice.audio")

# Phrases typiques inventées par Whisper sur du silence ou du bruit (sous-titres de vidéos).
_HALLUCINATIONS = re.compile(
    r"sous-titr|amara\.org|merci d'avoir regard|abonnez-vous|merci de votre attention"
    r"|^\W*$",
    re.IGNORECASE,
)


def wav_to_float(audio: PreparedAudio) -> np.ndarray:
    with wave.open(io.BytesIO(audio.data)) as wav:
        if wav.getsampwidth() != 2 or wav.getnchannels() != 1:
            raise AudioError("Format audio inattendu pour la transcription.")
        rate = wav.getframerate()
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    if rate != 16000:
        raise AudioError("La transcription attend un enregistrement à 16 kHz.", detail=f"{rate} Hz")
    return samples.astype(np.float32) / 32768.0


class LocalTranscriber:
    def __init__(
        self,
        model: str = "large-v3-turbo",
        *,
        language: str = "fr",
        compute_type: str = "int8",
        threads: int | None = None,
        prompt: str = "",
    ) -> None:
        self.model_name = model
        self.language = language
        self.compute_type = compute_type
        self.threads = threads or max(2, min(8, (os.cpu_count() or 4) // 2))
        self.prompt = prompt
        self._model = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self):  # type: ignore[no-untyped-def]
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise AudioError("Module faster-whisper absent.", detail=repr(exc)) from exc
            from alice.core.audio.models import whisper_dir

            started = time.perf_counter()
            try:
                self._model = WhisperModel(
                    self.model_name,
                    device="cpu",
                    compute_type=self.compute_type,
                    cpu_threads=self.threads,
                    download_root=str(whisper_dir()),
                )
            except Exception as exc:  # noqa: BLE001 - téléchargement, fichiers corrompus…
                raise AudioError(
                    f"Impossible de charger le modèle de transcription « {self.model_name} ». "
                    "Relance Installer_Alice.bat pour le (re)télécharger.",
                    detail=repr(exc),
                ) from exc
            log.info(
                "Whisper « %s » chargé en %.1f s (%s, %d threads)",
                self.model_name,
                time.perf_counter() - started,
                self.compute_type,
                self.threads,
            )
            return self._model

    def warm_up_async(self) -> None:
        """Charge le modèle en arrière-plan au démarrage : la 1re question n'attend pas."""

        def run() -> None:
            try:
                self.load()
            except AudioError as exc:
                log.error("Préchargement de Whisper : %s", exc.detail)

        threading.Thread(target=run, name="alice-whisper-load", daemon=True).start()

    def transcribe(self, audio: PreparedAudio) -> str:
        model = self.load()
        samples = wav_to_float(audio)
        started = time.perf_counter()
        segments, _info = model.transcribe(
            samples,
            language=self.language,
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
            initial_prompt=self.prompt or None,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        elapsed = time.perf_counter() - started
        if _HALLUCINATIONS.search(text):
            log.info("Transcription écartée (silence ou bruit) en %.2f s", elapsed)
            text = ""
        log.info(
            "Transcription locale : %d caractères en %.2f s pour %.1f s d'audio",
            len(text),
            elapsed,
            audio.duration_s,
        )
        return text
