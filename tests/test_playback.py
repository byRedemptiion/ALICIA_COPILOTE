import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal

import alicia.ui.playback as playback_module

Player = playback_module.QMediaPlayer


class FakeAudio(QObject):
    created = 0

    def __init__(self, parent=None):
        super().__init__(parent)
        type(self).created += 1
        self.volume = None

    def setVolume(self, value):
        self.volume = value


class FakePlayer(QObject):
    PlaybackState = Player.PlaybackState
    MediaStatus = Player.MediaStatus
    playbackStateChanged = Signal(object)
    mediaStatusChanged = Signal(object)
    errorOccurred = Signal(object)
    created = 0

    def __init__(self, parent=None):
        super().__init__(parent)
        type(self).created += 1
        self.source = None
        self.play_calls = 0

    def setAudioOutput(self, output):
        self.output = output

    def setSource(self, source):
        self.source = source

    def play(self):
        self.play_calls += 1

    def stop(self):
        self.playbackStateChanged.emit(self.PlaybackState.StoppedState)


@pytest.fixture
def playback(app, monkeypatch):
    FakeAudio.created = FakePlayer.created = 0
    monkeypatch.setattr(playback_module, "QAudioOutput", FakeAudio)
    monkeypatch.setattr(playback_module, "QMediaPlayer", FakePlayer)
    instance = playback_module.SpeechPlayback()
    yield instance
    instance.stop()


def test_audio_backend_is_not_created_until_first_play(playback):
    playback.set_volume(30)
    playback.stop()
    assert FakeAudio.created == FakePlayer.created == 0
    playback.play(b"RIFFtestWAVE")
    assert FakeAudio.created == FakePlayer.created == 1
    assert playback._audio.volume == 0.3


def test_volume_defaults_and_clamps(playback):
    playback.play(b"RIFFtestWAVE")
    assert playback._audio.volume == 0.55
    playback.set_volume(200)
    assert playback._audio.volume == 1
    playback.set_volume(-1)
    assert playback._audio.volume == 0


def test_temporary_wav_is_closed_before_reading_and_removed_on_stop(playback):
    playback.play(b"RIFFtestWAVE")
    audio_path = Path(playback._player.source.toLocalFile())
    assert audio_path.read_bytes() == b"RIFFtestWAVE"
    playback.stop()
    assert not audio_path.exists()
    assert playback._player.source.isEmpty()


def test_speaking_only_tracks_actual_playback_state(playback):
    speaking = []
    playback.speaking_changed.connect(speaking.append)
    playback.play(b"RIFFtestWAVE")
    assert True not in speaking
    playback._player.playbackStateChanged.emit(Player.PlaybackState.PlayingState)
    assert speaking[-1] is True
    playback._player.playbackStateChanged.emit(Player.PlaybackState.PausedState)
    assert speaking[-1] is False
    playback.stop()
    playback._player.playbackStateChanged.emit(Player.PlaybackState.PlayingState)
    assert speaking[-1] is False


def test_end_of_media_cleans_up_and_finishes_once(playback):
    finished = []
    playback.finished.connect(lambda: finished.append(True))
    playback.play(b"RIFFtestWAVE")
    audio_path = Path(playback._player.source.toLocalFile())
    playback._player.mediaStatusChanged.emit(Player.MediaStatus.EndOfMedia)
    playback._player.mediaStatusChanged.emit(Player.MediaStatus.EndOfMedia)
    assert len(finished) == 1
    assert not audio_path.exists()


def test_playback_error_is_safe_and_cleans_up(playback):
    finished, errors = [], []
    playback.finished.connect(lambda: finished.append(True))
    playback.failed.connect(errors.append)
    playback.play(b"RIFFtestWAVE")
    audio_path = Path(playback._player.source.toLocalFile())
    playback._player.errorOccurred.emit(Player.Error.ResourceError)
    assert len(finished) == len(errors) == 1
    assert str(audio_path) not in errors[0]
    assert not audio_path.exists()


def test_second_play_replaces_old_file_without_new_backend(playback):
    playback.play(b"RIFFtestWAVE")
    first_path = Path(playback._player.source.toLocalFile())
    playback.play(b"RIFFnextWAVE")
    second_path = Path(playback._player.source.toLocalFile())
    assert second_path.read_bytes() == b"RIFFnextWAVE"
    assert not first_path.exists()
    assert FakeAudio.created == FakePlayer.created == 1


def test_empty_audio_fails_without_creating_backend(playback):
    errors = []
    playback.failed.connect(errors.append)
    playback.play(b"")
    assert len(errors) == 1
    assert FakeAudio.created == FakePlayer.created == 0


def test_explicit_stop_ignores_late_media_events_without_replaying_audio(playback):
    finished, errors, speaking = [], [], []
    playback.finished.connect(lambda: finished.append(True))
    playback.failed.connect(errors.append)
    playback.speaking_changed.connect(speaking.append)
    playback.play(b"RIFFtestWAVE")
    player = playback._player
    path = Path(player.source.toLocalFile())
    playback.stop()
    player.mediaStatusChanged.emit(Player.MediaStatus.EndOfMedia)
    player.errorOccurred.emit(Player.Error.ResourceError)
    player.playbackStateChanged.emit(Player.PlaybackState.PlayingState)
    assert not playback.active
    assert not path.exists()
    assert player.source.isEmpty()
    assert player.play_calls == 1
    assert not finished
    assert not errors
    assert speaking[-1] is False
