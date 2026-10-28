"""Expressive French speech through a retained, isolated, offline worker."""

from __future__ import annotations

import base64
import io
import json
import math
import os
import queue
import subprocess
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path

from alicia.audio.chatterbox_setup import (
    _reference_is_valid,
    chatterbox_voice_is_present,
    runtime_python,
)
from alicia.audio.ports import SpeechError

MAX_MESSAGE_BYTES = 20 * 1024 * 1024
WORKER_TIMEOUT_SECONDS = 300


@dataclass(frozen=True, slots=True)
class ChatterboxSpeechSettings:
    runtime_directory: Path
    model_directory: Path
    reference_audio: Path | None = None
    device: str = "auto"
    exaggeration: float = 0.35
    cfg_weight: float = 0.5


def _read_responses(stream, messages: queue.Queue) -> None:
    try:
        while True:
            line = stream.readline(MAX_MESSAGE_BYTES + 1)
            if not line or len(line) > MAX_MESSAGE_BYTES:
                messages.put_nowait(None)
                return
            messages.put_nowait(json.loads(line))
    except (OSError, ValueError, queue.Full):
        try:
            messages.put_nowait(None)
        except queue.Full:
            pass


class ChatterboxSpeechProvider:
    """Keep model state warm; kill the worker on timeout, Stop/close or bad audio."""

    def __init__(self, settings: ChatterboxSpeechSettings) -> None:
        if settings.device not in {"auto", "cpu", "cuda"}:
            raise SpeechError("Le périphérique vocal doit être auto, cpu ou cuda.")
        for value in (settings.exaggeration, settings.cfg_weight):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SpeechError("Les paramètres d’expression vocale sont invalides.")
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise SpeechError("Les paramètres d’expression vocale sont invalides.")
        self.settings = settings
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._process = None
        self._messages: queue.Queue | None = None
        self._generation = 0

    def _command(self) -> list[str]:
        reference = self.settings.reference_audio or self.settings.model_directory / "reference.wav"
        return [
            str(runtime_python(self.settings.runtime_directory)),
            "-u",
            str(Path(__file__).with_name("chatterbox_worker.py")),
            str(self.settings.model_directory),
            str(reference),
            self.settings.device,
            str(self.settings.exaggeration),
            str(self.settings.cfg_weight),
        ]

    def _validate_installation(self) -> None:
        reference = self.settings.reference_audio or self.settings.model_directory / "reference.wav"
        if not chatterbox_voice_is_present(
            self.settings.runtime_directory, self.settings.model_directory
        ) or not _reference_is_valid(reference):
            raise SpeechError(
                "La voix expressive est absente ou incomplète. Relancez Installer_Alicia.bat "
                "pour préparer Chatterbox, ou sélectionnez explicitement la voix Kokoro."
            )

    def _receive(self, messages: queue.Queue, deadline: float):
        try:
            result = messages.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            self.close()
            raise SpeechError(
                "La voix expressive a dépassé son délai. Essayez une réponse plus courte "
                "ou sélectionnez explicitement Kokoro pour une voix plus légère."
            ) from None
        if not isinstance(result, dict) or result.get("error"):
            self.close()
            raise SpeechError("Le moteur de voix expressive est indisponible.")
        return result

    def _start(self, generation, deadline):
        self._validate_installation()
        environment = os.environ.copy()
        environment.update(
            {
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_DISABLE_TELEMETRY": "1",
                "DO_NOT_TRACK": "1",
                "TOKENIZERS_PARALLELISM": "false",
                "PYTHONIOENCODING": "utf-8",
            }
        )
        messages: queue.Queue = queue.Queue(maxsize=2)
        with self._state_lock:
            if generation != self._generation:
                raise SpeechError("La génération vocale a été arrêtée.")
            process = subprocess.Popen(
                self._command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=environment,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._process = process
            self._messages = messages
        threading.Thread(
            target=_read_responses, args=(process.stdout, messages), daemon=True
        ).start()
        if self._receive(messages, deadline).get("ready") is not True:
            self.close()
            raise SpeechError("Le moteur de voix expressive n’a pas démarré correctement.")
        return process, messages

    def synthesize(self, text: str) -> bytes:
        if not isinstance(text, str) or not text.strip() or len(text) > 4096:
            raise SpeechError("Le texte vocal est vide ou dépasse la longueur autorisée.")
        with self._lock:
            deadline = time.monotonic() + WORKER_TIMEOUT_SECONDS
            try:
                with self._state_lock:
                    process, messages = self._process, self._messages
                    generation = self._generation
                if process is None or process.poll() is not None:
                    process, messages = self._start(generation, deadline)
                payload = json.dumps({"text": text.strip()}, ensure_ascii=False).encode("utf-8")
                process.stdin.write(payload + b"\n")
                process.stdin.flush()
                result = self._receive(messages, deadline)
                content = base64.b64decode(result["wav"], validate=True)
                if len(content) > 15 * 1024 * 1024:
                    raise ValueError("Too much audio")
                with wave.open(io.BytesIO(content), "rb") as audio:
                    if (
                        audio.getnchannels() != 1
                        or audio.getsampwidth() != 2
                        or not 8000 <= audio.getframerate() <= 96000
                        or not 0 < audio.getnframes() / audio.getframerate() <= 300
                        or len(audio.readframes(audio.getnframes())) != audio.getnframes() * 2
                    ):
                        raise ValueError("Invalid audio")
                return content
            except SpeechError:
                raise
            except Exception:
                self.close()
                raise SpeechError("La voix expressive n’a pas pu générer la réponse.") from None

    def close(self) -> None:
        """Do not wait on a synthesis lock: Stop must be able to interrupt generation."""
        with self._state_lock:
            self._generation += 1
            process, self._process = self._process, None
            messages, self._messages = self._messages, None
        if messages is not None:
            try:
                messages.put_nowait(None)
            except queue.Full:
                pass
        if process is not None:
            try:
                process.terminate()
            except OSError:
                pass
            # Reaping and pipe closing stay off the Qt thread.
            threading.Thread(target=self._reap, args=(process,), daemon=True).start()

    @staticmethod
    def _reap(process) -> None:
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                pass
        finally:
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()
