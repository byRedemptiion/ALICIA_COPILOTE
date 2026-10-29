"""Réponse vocale interruptible, phrase par phrase.

Inspiré de RealtimeTTS (EdgeEngine, MIT) et de huburton/jarvis (lecture phrase par phrase
interruptible, MIT) : la phrase suivante est synthétisée pendant que la précédente est lue,
pour que la voix démarre vite. Voix Microsoft Edge (``edge-tts``) décodée par ``miniaudio`` :
aucun lecteur externe (mpv, ffmpeg) à installer sous Windows.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

import numpy as np

from alice.core.audio.devices import AudioError, device_name, find_device, sounddevice
from alice.core.audio.text import split_sentences
from alice.core.config import VoiceSettings

log = logging.getLogger("alice.audio")

TTS_SAMPLE_RATE = 24000
Synthesizer = Callable[[str], np.ndarray]  # phrase → échantillons int16 mono à 24 kHz


def edge_synthesizer(voice: str, rate: str) -> Synthesizer:
    def synthesize(text: str) -> np.ndarray:
        try:
            import edge_tts
            import miniaudio
        except ImportError as exc:
            raise AudioError(
                "Modules de voix absents (edge-tts, miniaudio).", detail=repr(exc)
            ) from exc

        async def fetch() -> bytes:
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            data = bytearray()
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio":
                    data.extend(chunk["data"])
            return bytes(data)

        try:
            mp3 = asyncio.run(fetch())
        except Exception as exc:  # noqa: BLE001 - réseau, voix inconnue, service changé
            raise AudioError(
                "La voix en ligne (Microsoft Edge) ne répond pas. Vérifie ta connexion ou "
                "le nom de la voix ([voice] tts_voice).",
                detail=repr(exc),
            ) from exc
        if not mp3:
            raise AudioError("La voix en ligne n'a renvoyé aucun son.", detail=f"voix {voice}")
        decoded = miniaudio.decode(
            mp3,
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=1,
            sample_rate=TTS_SAMPLE_RATE,
        )
        return np.frombuffer(decoded.samples, dtype=np.int16)

    return synthesize


class SoundDevicePlayer:
    """Lecture par blocs, arrêtable à tout moment."""

    def __init__(self, device: str = "") -> None:
        self.device = device

    def open(self):  # type: ignore[no-untyped-def]
        sd = sounddevice()
        index = find_device(self.device, output=True)
        stream = sd.OutputStream(
            samplerate=TTS_SAMPLE_RATE, channels=1, dtype="int16", device=index
        )
        stream.start()
        log.debug("Sortie audio : %s", device_name(index, output=True))
        return stream

    @staticmethod
    def play(stream, samples: np.ndarray, stop: threading.Event) -> None:  # type: ignore[no-untyped-def]
        block = TTS_SAMPLE_RATE // 20  # 50 ms : l'arrêt est quasi immédiat
        for start in range(0, len(samples), block):
            if stop.is_set():
                return
            stream.write(samples[start : start + block].reshape(-1, 1))

    @staticmethod
    def close(stream) -> None:  # type: ignore[no-untyped-def]
        try:
            stream.stop()
            stream.close()
        except Exception:  # noqa: BLE001
            pass


class Speaker:
    """Lit une réponse ; ``stop()`` coupe la voix immédiatement."""

    def __init__(
        self,
        settings: VoiceSettings,
        synthesizer: Synthesizer | None = None,
        player: SoundDevicePlayer | None = None,
    ) -> None:
        self.settings = settings
        self.synthesizer = synthesizer or edge_synthesizer(settings.tts_voice, settings.tts_rate)
        self.player = player or SoundDevicePlayer(settings.output_device)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.on_state: Callable[[str, str | None], None] = lambda _state, _msg: None

    @property
    def speaking(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def speak(self, text: str) -> bool:
        self.stop()
        sentences = split_sentences(text)
        if not sentences:
            return False
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, args=(sentences, self._stop), name="alice-voice", daemon=True
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        if self.speaking:
            self._stop.set()
            log.info("Voix coupée")
            self._thread.join(1.0)  # type: ignore[union-attr]

    def _run(self, sentences: list[str], stop: threading.Event) -> None:
        started = time.perf_counter()
        stream = None
        error: str | None = None
        pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="alice-tts")
        futures: list[Future] = [pool.submit(self.synthesizer, s) for s in sentences[:2]]
        try:
            for index in range(len(sentences)):
                if stop.is_set():
                    break
                samples = futures[index].result()
                if index + 2 < len(sentences):
                    futures.append(pool.submit(self.synthesizer, sentences[index + 2]))
                if stream is None:
                    stream = self.player.open()
                    log.info(
                        "Voix : 1re phrase prête en %d ms (%d phrases)",
                        (time.perf_counter() - started) * 1000,
                        len(sentences),
                    )
                    self.on_state("speaking", None)
                self.player.play(stream, samples, stop)
        except AudioError as exc:
            log.error("Voix : %s", exc.detail)
            error = exc.user_message
        except Exception as exc:  # noqa: BLE001
            log.error("Voix : erreur inattendue %r", exc)
            error = f"Erreur de lecture vocale : {exc!r}"
        finally:
            for future in futures:
                future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
            if stream is not None:
                # Laisse finir la dernière syllabe sauf si l'on a coupé.
                if not stop.is_set():
                    time.sleep(0.15)
                self.player.close(stream)
            self.on_state("error" if error else "idle", error)
