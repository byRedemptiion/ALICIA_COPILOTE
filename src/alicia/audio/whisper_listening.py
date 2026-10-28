"""French speech recognition on the PC, using a prepared Whisper model.

Only PCM capture runs in PortAudio's callback. Endpoint detection and inference
run on the recognition thread; no audio or transcription is sent to a service.
"""

from __future__ import annotations

import array
import logging
import math
import queue
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Any

from alicia.audio.listening import LocalListener, _load_sounddevice
from alicia.audio.ports import SpeechError

logger = logging.getLogger("alicia.audio.whisper")
_MAX_BUFFERED_BLOCKS = 120  # Six seconds of 50 ms mono PCM; discarded on pause/Stop.


def _rms(pcm: bytes) -> float:
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768


class _PhraseBuffer:
    """Bounded energy endpoint detector; Whisper's VAD filters the final phrase."""

    def __init__(self, sample_rate: int, silence_seconds: float = 0.7, *, interruption=False):
        self.sample_rate = sample_rate
        self.silence_limit = round(sample_rate * silence_seconds)
        self.pre_roll_limit = round(sample_rate * 0.25)
        self.maximum = sample_rate * (4 if interruption else 20)
        self.minimum_speech = round(sample_rate * (0.15 if interruption else 0.25))
        self.noise_floor = 0.002
        self.reset()

    def reset(self) -> None:
        self.pre_roll: deque[bytes] = deque()
        self.pre_roll_samples = 0
        self.frames: list[bytes] = []
        self.total = self.speech = self.silence = 0

    def push(self, data: bytes) -> bytes | None:
        if not data:
            return None
        count = len(data) // 2
        if count == 0:
            return None
        data = data[: count * 2]
        rms = _rms(data)
        voiced = rms >= max(0.006, self.noise_floor * 3)
        self.pre_roll.append(data)
        self.pre_roll_samples += count
        while self.pre_roll and self.pre_roll_samples > self.pre_roll_limit:
            excess = self.pre_roll_samples - self.pre_roll_limit
            first = self.pre_roll.popleft()
            removed = min(excess, len(first) // 2)
            if removed * 2 < len(first):
                self.pre_roll.appendleft(first[removed * 2 :])
            self.pre_roll_samples -= removed
        if not self.frames:
            if not voiced:
                self.noise_floor = max(0.0005, min(0.02, self.noise_floor * 0.98 + rms * 0.02))
                return None
            self.frames = list(self.pre_roll)
            self.total = self.pre_roll_samples
            self.speech = count
            self.silence = 0
        else:
            self.frames.append(data)
            self.total += count
            if voiced:
                self.speech += count
                self.silence = 0
            else:
                self.silence += count
        if self.silence < self.silence_limit and self.total < self.maximum:
            return None
        phrase = b"".join(self.frames) if self.speech >= self.minimum_speech else None
        self.reset()
        return phrase


def _resample_audio(pcm: bytes, sample_rate: int):
    import numpy as np

    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
    if sample_rate != 16000:
        from scipy.signal import resample_poly

        divisor = math.gcd(sample_rate, 16000)
        samples = resample_poly(samples, 16000 // divisor, sample_rate // divisor)
    return np.asarray(samples, dtype=np.float32)


def _load_whisper():
    try:
        from faster_whisper import WhisperModel
    except (ImportError, OSError):
        raise SpeechError(
            "Whisper local est indisponible. Relancez Installer_Alicia.bat pour préparer la reconnaissance."
        ) from None
    return WhisperModel, _load_sounddevice()


def _decode(engine, pcm: bytes, sample_rate: int, *, interruption=False) -> str:
    samples = _resample_audio(pcm, sample_rate)
    segments, _information = engine.transcribe(
        samples,
        language="fr",
        task="transcribe",
        beam_size=1 if interruption else 5,
        temperature=0.0,
        vad_filter=True,
        vad_parameters={
            "min_speech_duration_ms": 150 if interruption else 250,
            "min_silence_duration_ms": 200 if interruption else 300,
            "speech_pad_ms": 200,
        },
        condition_on_previous_text=False,
        initial_prompt="Alicia.",
        no_speech_threshold=0.6,
        log_prob_threshold=-0.8,
        compression_ratio_threshold=2.4,
        repetition_penalty=1.1,
        no_repeat_ngram_size=3,
        word_timestamps=True,
        hallucination_silence_threshold=1.0,
    )
    pieces = []
    for segment in segments:
        text = getattr(segment, "text", "")
        if not isinstance(text, str) or not text.strip():
            continue
        log_probability = getattr(segment, "avg_logprob", -100)
        no_speech = getattr(segment, "no_speech_prob", 1)
        compression = getattr(segment, "compression_ratio", 0)
        if not all(
            isinstance(value, (int, float)) and math.isfinite(value)
            for value in (log_probability, no_speech, compression)
        ):
            return ""
        # Reject the complete phrase when a segment is unreliable. Joining words
        # from either side of a missing segment can turn a question into another
        # request, particularly with negations. Never repair it using an LLM.
        if log_probability < -0.8 or no_speech > 0.6 or compression > 2.4:
            return ""
        probabilities = [
            getattr(word, "probability", None) for word in (getattr(segment, "words", None) or [])
        ]
        if probabilities and (
            not all(
                isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 1
                for value in probabilities
            )
            or sum(probabilities) / len(probabilities) < 0.45
        ):
            return ""
        pieces.append(text.strip())
    text = " ".join(pieces)
    return text if len(text) <= 2000 else ""


def _transcribe(engine, pcm: bytes, sample_rate: int) -> str:
    return _decode(engine, pcm, sample_rate)


def _transcribe_interruption(engine, pcm: bytes, sample_rate: int) -> str:
    return _decode(engine, pcm, sample_rate, interruption=True)


def _cuda_is_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except (ImportError, OSError, RuntimeError):
        return False


def _probe_cuda_engine(engine) -> None:
    """Force one local encoder/decode pass: CUDA DLL loading can be lazy."""
    import numpy as np

    segments, _ = engine.transcribe(
        np.zeros(8000, dtype=np.float32),
        language="fr",
        beam_size=1,
        temperature=0.0,
        vad_filter=False,
        condition_on_previous_text=False,
    )
    for _segment in segments:
        pass


def _create_engine(factory, model_path: Path, device: str):
    options = {
        "local_files_only": True,
        "cpu_threads": 4,
        "num_workers": 1,
    }
    if device == "auto" and _cuda_is_available():
        try:
            engine = factory(str(model_path), device="cuda", compute_type="float16", **options)
            _probe_cuda_engine(engine)
            return engine
        except Exception as error:
            # No raw driver error or environment detail enters the logs. A
            # missing cuDNN library must not make automatic listening unusable.
            logger.info("recognition_gpu_unavailable kind=%s", type(error).__name__)
            engine = None
    selected = "cpu" if device == "auto" else device
    return factory(
        str(model_path),
        device=selected,
        compute_type="int8" if selected == "cpu" else "float16",
        **options,
    )


class WhisperListener(LocalListener):
    """Keep the existing bounded listener lifecycle with more accurate decoding.

    Automatic mode probes local CUDA and falls back to local CPU int8 when its
    libraries are unavailable. Explicit CUDA keeps a visible failure.
    """

    def __init__(
        self,
        model_path: Path,
        on_text,
        on_error,
        on_activity,
        on_partial=None,
        *,
        backend: tuple[Any, Any] | None = None,
        device: str = "auto",
    ):
        if device not in {"auto", "cpu", "cuda"}:
            raise SpeechError("Le périphérique Whisper doit être auto, cpu ou cuda.")
        super().__init__(model_path, on_text, on_error, on_activity, on_partial, backend=backend)
        self.device = device
        self._decoding = threading.Event()
        self._interruption_mode = False
        self._audio = queue.Queue(maxsize=_MAX_BUFFERED_BLOCKS)

    def start(self, device_index: int | None = None) -> None:
        from alicia.audio.whisper_setup import whisper_model_is_present

        if not whisper_model_is_present(self.model_path):
            raise SpeechError(
                "Le modèle Whisper local est absent ou incomplet. Relancez Installer_Alicia.bat."
            )
        super().start(device_index)

    def set_interruption_mode(self, enabled: bool) -> None:
        """Select short-command decoding without opening or resuming a stream.

        The UI still owns pause/resume and accepts only an explicit stop phrase
        while playing. The new epoch invalidates any prior inference result.
        """
        with self._lock:
            enabled = bool(enabled)
            if self._interruption_mode == enabled:
                return
            self._interruption_mode = enabled
            self._epoch += 1
            self._discard_audio()

    def _run(self, generation: int, device_index: int | None) -> None:
        try:
            factory, sounddevice = self._backend or _load_whisper()
            engine = _create_engine(factory, self.model_path, self.device)
            if self._stopping.is_set():
                return
            device = sounddevice.query_devices(device_index, "input")
            rate = float(device.get("default_samplerate", 0))
            if (
                not math.isfinite(rate)
                or not 8000 <= rate <= 192000
                or device.get("max_input_channels", 0) < 1
            ):
                raise SpeechError("Le microphone sélectionné ne fournit pas une entrée compatible.")
            sample_rate = round(rate)

            def audio_callback(indata, _frames, _time_info, status):
                self._put_audio(generation, indata, status)

            with sounddevice.RawInputStream(
                samplerate=sample_rate,
                blocksize=round(sample_rate * 0.05),
                device=device_index,
                dtype="int16",
                channels=1,
                callback=audio_callback,
            ):
                with self._lock:
                    if generation != self._generation or not self._running:
                        return
                    self._callback(self.on_activity, True)
                self._consume(generation, engine, sample_rate)
        except Exception as error:
            logger.warning("recognition_failed kind=%s", type(error).__name__)
            message = (
                str(error)
                if isinstance(error, SpeechError)
                else (
                    "Whisper ou le microphone est indisponible. Vérifiez le modèle local, "
                    "le périphérique et les dépendances. Pour CUDA, vérifiez les bibliothèques GPU."
                )
            )
            with self._lock:
                if generation == self._generation and self._running:
                    self._callback(self.on_error, message)
        finally:
            self._decoding.clear()
            with self._lock:
                if generation == self._generation:
                    self._running = False
                    self._callback(self.on_activity, False)
                if self._thread is threading.current_thread():
                    self._thread = None

    def _consume(self, generation: int, engine, sample_rate: int) -> None:
        segmenter = _PhraseBuffer(sample_rate)
        previous_epoch = None
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
            if epoch != previous_epoch:
                with self._lock:
                    interruption = self._interruption_mode
                segmenter = _PhraseBuffer(
                    sample_rate,
                    silence_seconds=0.35 if interruption else 0.7,
                    interruption=interruption,
                )
                previous_epoch = epoch
            phrase = segmenter.push(data)
            if phrase is None:
                continue
            self._decoding.set()
            try:
                transcribe = _transcribe_interruption if interruption else _transcribe
                text = transcribe(engine, phrase, sample_rate)
                self._emit_text(generation, epoch, text)
            finally:
                self._decoding.clear()
