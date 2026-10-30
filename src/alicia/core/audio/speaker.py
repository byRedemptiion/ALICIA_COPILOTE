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

from alicia.core.audio.devices import AudioError, device_name, find_device, sounddevice
from alicia.core.audio.text import split_sentences
from alicia.core.config import VoiceSettings

log = logging.getLogger("alicia.audio")

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


def kokoro_synthesizer(voice: str, speed: float, lang: str = "fr-fr") -> Synthesizer:
    """Voix Kokoro locale (ONNX, processeur) : gratuite, hors ligne, ne prend pas le GPU."""
    state: dict[str, object] = {}
    lock = threading.Lock()

    def engine():  # type: ignore[no-untyped-def]
        with lock:
            if "kokoro" not in state:
                from alicia.core.audio.models import kokoro_paths, kokoro_ready

                if not kokoro_ready():
                    raise AudioError(
                        "La voix Kokoro n'est pas installée. Relance Installer_Alicia.bat ou "
                        "lance : alicia-diag prepare-voice",
                        detail="fichiers Kokoro absents",
                    )
                try:
                    from kokoro_onnx import Kokoro
                except ImportError as exc:
                    raise AudioError("Module kokoro-onnx absent.", detail=repr(exc)) from exc
                started = time.perf_counter()
                model, voices = kokoro_paths()
                state["kokoro"] = Kokoro(str(model), str(voices))
                log.info("Kokoro chargé en %.1f s", time.perf_counter() - started)
            return state["kokoro"]

    def synthesize(text: str) -> np.ndarray:
        kokoro = engine()
        with lock:  # une synthèse à la fois : la session ONNX utilise déjà tous les cœurs prévus
            try:
                audio, rate = kokoro.create(text, voice=voice, speed=speed, lang=lang)  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                raise AudioError("La voix Kokoro a échoué.", detail=repr(exc)) from exc
        if rate != TTS_SAMPLE_RATE:
            raise AudioError("Fréquence inattendue pour Kokoro.", detail=f"{rate} Hz")
        return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)

    synthesize.warm_up = engine  # type: ignore[attr-defined]
    return synthesize


OPENAI_VOICE_STYLE = (
    "Parle en français naturel, comme une coéquipière de jeu vidéo : ton chaleureux, "
    "vif et complice, phrases courtes, sans lire la ponctuation ni les symboles."
)


def openai_synthesizer(settings: VoiceSettings) -> Synthesizer:
    """Voix OpenAI (API audio/speech) : très naturelle, payante à l'usage."""
    import httpx

    percent = 0
    try:
        percent = int(settings.tts_rate.strip().rstrip("%"))
    except ValueError:
        pass
    pace = (
        "" if abs(percent) < 5 else (" Parle un peu vite." if percent > 0 else " Parle posément.")
    )

    def synthesize(text: str) -> np.ndarray:
        if not settings.openai_key:
            raise AudioError(
                "Voix OpenAI : il faut une clé OpenAI (bouton IA → ChatGPT), ou choisis la voix "
                "Edge dans les réglages.",
                detail="OPENAI_API_KEY absente",
            )
        try:
            response = httpx.post(
                f"{settings.openai_base_url}/audio/speech",
                headers={"Authorization": f"Bearer {settings.openai_key.get()}"},
                json={
                    "model": settings.openai_tts_model,
                    "voice": settings.openai_voice,
                    "input": text,
                    "instructions": OPENAI_VOICE_STYLE + pace,
                    "response_format": "pcm",  # 24 kHz, 16 bits, mono
                },
                timeout=30,
            )
        except httpx.HTTPError as exc:
            raise AudioError("Voix OpenAI injoignable.", detail=repr(exc)) from exc
        if response.status_code == 401:
            raise AudioError("Voix OpenAI : clé refusée.", detail="HTTP 401")
        if response.status_code == 429:
            raise AudioError(
                "Voix OpenAI : plus de crédit ou trop de demandes.", detail=response.text[:200]
            )
        if response.status_code >= 400:
            raise AudioError(
                f"Voix OpenAI : erreur {response.status_code}.", detail=response.text[:300]
            )
        data = response.content
        return np.frombuffer(data[: len(data) - len(data) % 2], dtype=np.int16)

    return synthesize


def make_synthesizer(settings: VoiceSettings) -> Synthesizer:
    if settings.tts_engine == "openai":
        return openai_synthesizer(settings)
    if settings.tts_engine == "kokoro":
        return kokoro_synthesizer(settings.kokoro_voice, settings.kokoro_speed)
    return edge_synthesizer(settings.tts_voice, settings.tts_rate)


class SoundDevicePlayer:
    """Lecture par blocs, arrêtable à tout moment."""

    def __init__(self, device: str = "") -> None:
        self.device = device
        self.level = 0.0  # niveau de la voix en cours (0-1), lu par l'interface

    def open(self):  # type: ignore[no-untyped-def]
        sd = sounddevice()
        index = find_device(self.device, output=True)
        stream = sd.OutputStream(
            samplerate=TTS_SAMPLE_RATE, channels=1, dtype="int16", device=index
        )
        stream.start()
        log.debug("Sortie audio : %s", device_name(index, output=True))
        return stream

    def play(self, stream, samples: np.ndarray, stop: threading.Event) -> None:  # type: ignore[no-untyped-def]
        block = TTS_SAMPLE_RATE // 20  # 50 ms : l'arrêt est quasi immédiat
        try:
            for start in range(0, len(samples), block):
                if stop.is_set():
                    return
                chunk = samples[start : start + block]
                self.level = float(np.abs(chunk).max()) / 32768.0 if len(chunk) else 0.0
                stream.write(chunk.reshape(-1, 1))
        finally:
            self.level = 0.0

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
        self.synthesizer = synthesizer or make_synthesizer(settings)
        self.player = player or SoundDevicePlayer(settings.output_device)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.on_state: Callable[[str, str | None], None] = lambda _state, _msg: None

    @property
    def level(self) -> float:
        return float(getattr(self.player, "level", 0.0)) if self.speaking else 0.0

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
            target=self._run, args=(sentences, self._stop), name="alicia-voice", daemon=True
        )
        self._thread.start()
        return True

    def warm_up_async(self) -> None:
        """Charge un moteur local (Kokoro) en arrière-plan pour que la 1re réponse parte vite."""
        warm = getattr(self.synthesizer, "warm_up", None)
        if warm is None:
            return

        def run() -> None:
            try:
                warm()
            except AudioError as exc:
                log.error("Préchargement de la voix : %s", exc.detail)

        threading.Thread(target=run, name="alicia-voice-load", daemon=True).start()

    def stop(self) -> None:
        if self.speaking:
            self._stop.set()
            log.info("Voix coupée")
            self._thread.join(1.0)  # type: ignore[union-attr]

    def _run(self, sentences: list[str], stop: threading.Event) -> None:
        started = time.perf_counter()
        stream = None
        error: str | None = None
        pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="alicia-tts")
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
