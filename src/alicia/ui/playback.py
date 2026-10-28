"""Play generated speech and expose actual playback activity to the avatar."""

from pathlib import Path

from PySide6.QtCore import QDir, QObject, QTemporaryDir, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer


class SpeechPlayback(QObject):
    speaking_changed = Signal(bool)
    failed = Signal(str)
    finished = Signal()

    @property
    def active(self) -> bool:
        return self._active

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._directory: QTemporaryDir | None = None
        self._active = False
        self._cleaning = False
        self._volume = 0.55
        self._audio: QAudioOutput | None = None
        self._player: QMediaPlayer | None = None

    def _ensure_player(self) -> QMediaPlayer:
        if self._player is not None:
            return self._player
        self._audio = QAudioOutput(self)
        self._audio.setVolume(self._volume)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio)
        self._player.playbackStateChanged.connect(self._on_playback_state)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_error)
        return self._player

    def set_volume(self, volume: int) -> None:
        self._volume = max(0, min(100, volume)) / 100
        if self._audio is not None:
            self._audio.setVolume(self._volume)

    def play(self, wav: bytes) -> None:
        self.stop()
        if not wav:
            self.failed.emit("Le fichier vocal est vide.")
            self.finished.emit()
            return

        directory = QTemporaryDir(QDir.tempPath() + "/alicia-speech-XXXXXX")
        if not directory.isValid():
            self.failed.emit("Impossible de préparer la lecture vocale temporaire.")
            self.finished.emit()
            return
        self._directory = directory
        audio_path = Path(directory.path()) / "speech.wav"
        try:
            # Closing the writer before playback is required on Windows.
            audio_path.write_bytes(wav)
        except OSError:
            self.stop()
            self.failed.emit("Impossible de préparer la lecture vocale temporaire.")
            self.finished.emit()
            return

        try:
            player = self._ensure_player()
        except Exception:
            self.stop()
            self.failed.emit("Impossible d’initialiser la sortie audio.")
            self.finished.emit()
            return
        self._active = True
        player.setSource(QUrl.fromLocalFile(str(audio_path)))
        if self._active:
            player.play()

    def stop(self) -> None:
        if self._cleaning:
            return
        self._cleaning = True
        self._active = False
        try:
            if self._player is not None:
                self._player.stop()
                self._player.setSource(QUrl())
            self.speaking_changed.emit(False)
            if self._directory is not None:
                self._directory.remove()
                self._directory = None
        finally:
            self._cleaning = False

    def _on_playback_state(self, state: QMediaPlayer.PlaybackState) -> None:
        self.speaking_changed.emit(
            self._active and state == QMediaPlayer.PlaybackState.PlayingState
        )

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if self._active and status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.stop()
            self.finished.emit()

    def _on_error(self, *args: object) -> None:
        if not self._active or self._cleaning:
            return
        self.stop()
        self.failed.emit("Lecture audio impossible. Vérifiez la sortie audio et son volume.")
        self.finished.emit()
