"""Bounded, offline microphone recognition with Vosk.

Callbacks run on the recognition thread and must return promptly. The desktop
adapter forwards them through Qt signals; this module has no dependency on Qt.
"""

from __future__ import annotations

import json
import logging
import math
import queue
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from alicia.audio.ports import SpeechError

logger = logging.getLogger("alicia.audio.listening")
_QUEUE_BLOCKS = 8
_MAX_PHRASE_SECONDS = 20


def _load_sounddevice():
    try:
        import sounddevice
    except (ImportError, OSError):
        raise SpeechError(
            "Le microphone local est indisponible. Relancez Installer_Alicia.bat "
            "pour préparer les dépendances audio."
        ) from None
    return sounddevice


def _load_backend():
    try:
        import vosk
    except (ImportError, OSError):
        raise SpeechError(
            "La reconnaissance vocale locale est indisponible. Relancez Installer_Alicia.bat."
        ) from None
    return vosk, _load_sounddevice()


def list_input_devices() -> list[tuple[int, str]]:
    """List local microphones without opening or recording any of them."""
    try:
        devices = _load_sounddevice().query_devices()
        return [
            (index, str(device.get("name") or f"Microphone {index}"))
            for index, device in enumerate(devices)
            if device.get("max_input_channels", 0) > 0
        ]
    except SpeechError:
        raise
    except Exception:
        raise SpeechError(
            "Impossible de lister les microphones. Vérifiez les périphériques "
            "audio et l’autorisation d’accès au microphone."
        ) from None


def _recognized_text(payload: str, field: str) -> str:
    try:
        result = json.loads(payload)
    except (TypeError, ValueError):
        return ""
    value = result.get(field) if isinstance(result, dict) else None
    return value.strip() if isinstance(value, str) else ""


class LocalListener:
    def __init__(
        self,
        model_path: Path,
        on_text: Callable[[str], None],
        on_error: Callable[[str], None],
        on_activity: Callable[[bool], None],
        on_partial: Callable[[str], None] | None = None,
        *,
        backend: tuple[Any, Any] | None = None,
    ) -> None:
        self.model_path = Path(model_path)
        self.on_text = on_text
        self.on_error = on_error
        self.on_activity = on_activity
        self.on_partial = on_partial
        self._backend = backend
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._generation = 0
        self._epoch = 0
        self._paused = threading.Event()
        self._stopping = threading.Event()
        self._audio: queue.Queue[tuple[int, bytes]] = queue.Queue(maxsize=_QUEUE_BLOCKS)

    @property
    def active(self) -> bool:
        """Whether listening is enabled, including temporary processing pauses."""
        with self._lock:
            return self._running

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def start(self, device_index: int | None = None) -> None:
        if device_index is not None and (
            isinstance(device_index, bool) or not isinstance(device_index, int) or device_index < 0
        ):
            raise SpeechError("Sélectionnez un microphone valide.")
        if not self.model_path.is_dir():
            raise SpeechError(
                "Le modèle vocal français local est absent. "
                "Relancez Installer_Alicia.bat avant d’activer le microphone."
            )
        with self._lock:
            if self._running:
                return
            if self._thread is not None and self._thread.is_alive():
                raise SpeechError("Le microphone termine son arrêt. Réessayez dans un instant.")
            self._generation += 1
            generation = self._generation
            self._epoch += 1
            self._paused.clear()
            self._stopping.clear()
            self._discard_audio()
            self._running = True
            self._thread = threading.Thread(
                target=self._run,
                args=(generation, device_index),
                name="alicia-listening",
                daemon=True,
            )
            self._thread.start()

    def pause(self) -> None:
        with self._lock:
            self._paused.set()
            self._epoch += 1
            self._discard_audio()

    def resume(self) -> None:
        with self._lock:
            self._epoch += 1
            self._discard_audio()
            self._paused.clear()

    def stop(self) -> None:
        with self._lock:
            was_running = self._running
            self._running = False
            self._generation += 1
            self._epoch += 1
            self._stopping.set()
            self._paused.set()
            self._discard_audio()
            thread = self._thread
            if was_running:
                self._callback(self.on_activity, False)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.2)

    def _discard_audio(self) -> None:
        while True:
            try:
                self._audio.get_nowait()
            except queue.Empty:
                return

    def _put_audio(self, generation: int, indata: Any, status: Any) -> None:
        # PortAudio calls this frequently; never wait on a full queue.
        with self._lock:
            if (
                generation != self._generation
                or not self._running
                or self._stopping.is_set()
                or self._paused.is_set()
            ):
                return
            if status:
                self._epoch += 1
                self._discard_audio()
            item = (self._epoch, bytes(indata))
            try:
                self._audio.put_nowait(item)
            except queue.Full:
                self._discard_audio()
                self._epoch += 1
                self._audio.put_nowait((self._epoch, item[1]))

    def _emit_text(self, generation: int, epoch: int, text: str, partial=False) -> None:
        if not text:
            return
        with self._lock:
            if (
                generation != self._generation
                or epoch != self._epoch
                or not self._running
                or self._paused.is_set()
                or self._stopping.is_set()
            ):
                return
            callback = self.on_partial if partial else self.on_text
            if callback is not None:
                self._callback(callback, text)

    @staticmethod
    def _callback(callback, value) -> None:
        try:
            callback(value)
        except Exception as error:
            logger.warning("listener_callback_failed kind=%s", type(error).__name__)

    def _run(self, generation: int, device_index: int | None) -> None:
        try:
            vosk, sounddevice = self._backend or _load_backend()
            vosk.SetLogLevel(-1)
            model = vosk.Model(str(self.model_path))
            if self._stopping.is_set():
                return
            device = sounddevice.query_devices(device_index, "input")
            sample_rate = float(device.get("default_samplerate", 0))
            if (
                not math.isfinite(sample_rate)
                or not 8000 <= sample_rate <= 192000
                or device.get("max_input_channels", 0) < 1
            ):
                raise SpeechError(
                    "Le microphone sélectionné ne fournit pas d’entrée audio compatible."
                )
            recognizer = vosk.KaldiRecognizer(model, sample_rate)
            blocksize = max(800, int(sample_rate * 0.1))

            def audio_callback(indata, _frames, _time_info, status):
                self._put_audio(generation, indata, status)

            with sounddevice.RawInputStream(
                samplerate=sample_rate,
                blocksize=blocksize,
                device=device_index,
                dtype="int16",
                channels=1,
                callback=audio_callback,
            ):
                with self._lock:
                    if generation != self._generation or not self._running:
                        return
                    self._callback(self.on_activity, True)
                self._consume(generation, recognizer, sample_rate)
        except Exception as error:
            logger.warning("listener_failed kind=%s", type(error).__name__)
            message = (
                str(error)
                if isinstance(error, SpeechError)
                else "Le microphone ou la reconnaissance locale est indisponible. "
                "Vérifiez l’autorisation microphone, le périphérique choisi et le modèle installé."
            )
            with self._lock:
                if generation == self._generation and self._running:
                    self._callback(self.on_error, message)
        finally:
            with self._lock:
                if generation == self._generation:
                    self._running = False
                    self._callback(self.on_activity, False)
                if self._thread is threading.current_thread():
                    self._thread = None

    def _consume(self, generation: int, recognizer: Any, sample_rate: float) -> None:
        segment_frames = 0
        previous_partial = ""
        recognizer_epoch = None
        while not self._stopping.is_set():
            try:
                epoch, data = self._audio.get(timeout=0.1)
            except queue.Empty:
                continue
            with self._lock:
                current = (
                    generation == self._generation
                    and self._running
                    and not self._paused.is_set()
                    and epoch == self._epoch
                )
            if not current:
                continue
            if recognizer_epoch != epoch:
                recognizer.Reset()
                segment_frames = 0
                previous_partial = ""
                recognizer_epoch = epoch
            segment_frames += len(data) // 2
            complete = recognizer.AcceptWaveform(data)
            if complete:
                text = _recognized_text(recognizer.Result(), "text")
                self._emit_text(generation, epoch, text)
                segment_frames = 0
                previous_partial = ""
            elif segment_frames >= sample_rate * _MAX_PHRASE_SECONDS:
                text = _recognized_text(recognizer.FinalResult(), "text")
                self._emit_text(generation, epoch, text)
                recognizer.Reset()
                segment_frames = 0
                previous_partial = ""
            elif self.on_partial is not None:
                partial = _recognized_text(recognizer.PartialResult(), "partial")
                if partial != previous_partial:
                    self._emit_text(generation, epoch, partial, partial=True)
                    previous_partial = partial
