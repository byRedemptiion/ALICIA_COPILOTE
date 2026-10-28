"""Voix neuronale française locale, sans service distant ni clonage vocal."""

from __future__ import annotations

import io
import logging
import math
import re
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alicia.audio.ports import SpeechError

logger = logging.getLogger("alicia.audio.kokoro")
MAX_AUDIO_SECONDS = 300


@dataclass(frozen=True, slots=True)
class KokoroSpeechSettings:
    model_directory: Path
    voice: str = "ff_siwis"
    speed: float = 0.95


class KokoroSpeechProvider:
    """Crée du WAV à la demande ; le premier chargement est conservé en mémoire."""

    def __init__(self, settings: KokoroSpeechSettings, engine: Any = None) -> None:
        if not isinstance(settings.voice, str) or not re.fullmatch(
            r"ff_[a-z0-9_]+", settings.voice
        ):
            raise SpeechError(
                "Choisissez une voix française féminine Kokoro, par exemple ff_siwis."
            )
        try:
            speed = float(settings.speed)
        except (ValueError, TypeError):
            speed = float("nan")
        if isinstance(settings.speed, bool) or not math.isfinite(speed) or not 0.7 <= speed <= 1.3:
            raise SpeechError(
                "La vitesse de la voix naturelle doit être comprise entre 0,7 et 1,3."
            )
        self.settings = settings
        self._speed = speed
        self._engine = engine
        self._lock = threading.Lock()

    def _load_engine(self):
        from alicia.audio.neural_setup import neural_voice_is_present

        directory = Path(self.settings.model_directory)
        if not neural_voice_is_present(directory):
            raise SpeechError(
                "Le modèle de voix naturelle est absent ou incomplet. "
                "Relancez Installer_Alicia.bat pour le préparer."
            )
        try:
            import onnxruntime
            from kokoro_onnx import Kokoro

            onnxruntime.disable_telemetry_events()
            # Leave CPU/GPU capacity for the game and the visual model.
            options = onnxruntime.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            options.log_severity_level = 3
            session = onnxruntime.InferenceSession(
                str(directory / "kokoro-v1.0.onnx"),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
            return Kokoro.from_session(session, str(directory / "voices-v1.0.bin"))
        except Exception:
            raise SpeechError(
                "Le moteur vocal naturel est indisponible. Relancez l’installation "
                "et vérifiez les fichiers Kokoro et les dépendances audio."
            ) from None

    def synthesize(self, text: str) -> bytes:
        if not isinstance(text, str) or not text.strip():
            raise SpeechError("Aucun texte à lire.")
        if len(text) > 4096:
            raise SpeechError("La réponse dépasse la longueur maximale de lecture vocale.")
        started = time.monotonic()
        with self._lock:
            if self._engine is None:
                self._engine = self._load_engine()
            try:
                import numpy as np

                samples, sample_rate = self._engine.create(
                    text.strip(),
                    voice=self.settings.voice,
                    speed=self._speed,
                    lang="fr-fr",
                )
                if (
                    isinstance(sample_rate, bool)
                    or not isinstance(sample_rate, (int, np.integer))
                    or not 8000 <= sample_rate <= 96000
                ):
                    raise ValueError("Invalid sample rate")
                samples = np.asarray(samples)
                if (
                    samples.ndim != 1
                    or not 0 < samples.size <= sample_rate * MAX_AUDIO_SECONDS
                    or not np.isfinite(samples).all()
                ):
                    raise ValueError("Invalid audio samples")
                pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
                output = io.BytesIO()
                with wave.open(output, "wb") as writer:
                    writer.setnchannels(1)
                    writer.setsampwidth(2)
                    writer.setframerate(int(sample_rate))
                    writer.writeframes(pcm)
            except Exception:
                raise SpeechError(
                    "La voix naturelle n’a pas pu générer la réponse. "
                    "Vérifiez les fichiers du modèle et la voix sélectionnée."
                ) from None
        logger.info(
            "local_neural_speech_completed duration_seconds=%.3f", time.monotonic() - started
        )
        return output.getvalue()
