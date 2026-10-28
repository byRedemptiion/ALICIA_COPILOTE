import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from alicia.audio import listening
from alicia.audio.listening import LocalListener, list_input_devices
from alicia.audio.ports import SpeechError


class FakeRecognizer:
    def __init__(self):
        self.chunks = []
        self.resets = 0
        self.text = "bonjour Alicia"
        self.partial = "bonjour"
        self.complete = True
        self.accepted = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def Reset(self):
        self.resets += 1

    def AcceptWaveform(self, data):
        self.chunks.append(data)
        self.accepted.set()
        self.release.wait(timeout=3)
        return self.complete

    def Result(self):
        return json.dumps({"text": self.text})

    def PartialResult(self):
        return json.dumps({"partial": self.partial})

    def FinalResult(self):
        return json.dumps({"text": "phrase finale longue"})


class FakeAudio:
    def __init__(self):
        self.options = None
        self.callback = None
        self.closed = threading.Event()
        self.query_error = None
        self.device = {"default_samplerate": 16000, "max_input_channels": 1}

    def query_devices(self, _device, _kind):
        if self.query_error:
            raise self.query_error
        return self.device

    def RawInputStream(self, **options):
        self.options = options
        self.callback = options["callback"]
        audio = self

        class Stream:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                audio.closed.set()

        return Stream()

    def feed(self, data=b"\x01\x00" * 1600, status=None):
        self.callback(data, len(data) // 2, None, status)


@pytest.fixture
def listener_fixture(tmp_path):
    model = tmp_path / "vosk-model-small-fr-0.22"
    model.mkdir()
    rec = FakeRecognizer()
    audio = FakeAudio()
    vosk = SimpleNamespace(
        SetLogLevel=Mock(),
        Model=Mock(return_value=object()),
        KaldiRecognizer=Mock(return_value=rec),
    )
    texts, partials, errors, states = [], [], [], []
    heard, failed, opened = threading.Event(), threading.Event(), threading.Event()

    def on_text(text):
        texts.append(text)
        heard.set()

    def on_error(error):
        errors.append(error)
        failed.set()

    def on_activity(active):
        states.append(active)
        if active:
            opened.set()

    listener = LocalListener(
        model, on_text, on_error, on_activity, partials.append, backend=(vosk, audio)
    )
    result = SimpleNamespace(
        listener=listener,
        rec=rec,
        audio=audio,
        vosk=vosk,
        texts=texts,
        partials=partials,
        errors=errors,
        states=states,
        heard=heard,
        failed=failed,
        opened=opened,
    )
    yield result
    rec.release.set()
    listener.stop()
    if audio.callback is not None:
        audio.closed.wait(timeout=1)


def start(fixture):
    fixture.listener.start()
    assert fixture.opened.wait(timeout=2), fixture.errors


def test_microphone_is_closed_until_explicit_start(listener_fixture):
    fixture = listener_fixture
    assert not fixture.listener.active
    assert fixture.audio.callback is None
    fixture.vosk.Model.assert_not_called()
    start(fixture)
    assert fixture.listener.active
    assert fixture.audio.options["channels"] == 1
    assert fixture.audio.options["dtype"] == "int16"
    assert fixture.audio.options["samplerate"] == 16000


def test_final_phrase_only_is_delivered(listener_fixture):
    fixture = listener_fixture
    start(fixture)
    fixture.audio.feed()
    assert fixture.heard.wait(timeout=2)
    assert fixture.texts == ["bonjour Alicia"]
    fixture.listener.stop()
    assert fixture.states == [True, False]


def test_partial_phrase_does_not_trigger_a_question(listener_fixture):
    fixture = listener_fixture
    fixture.rec.complete = False
    start(fixture)
    fixture.audio.feed()
    assert fixture.rec.accepted.wait(timeout=2)
    fixture.listener.stop()
    assert fixture.texts == []
    assert fixture.partials in (["bonjour"], [])  # Stop may invalidate the in-flight partial.


def test_pause_discards_inflight_result_and_new_audio(listener_fixture):
    fixture = listener_fixture
    fixture.rec.release.clear()
    start(fixture)
    fixture.audio.feed(b"before pause")
    assert fixture.rec.accepted.wait(timeout=2)
    fixture.listener.pause()
    fixture.audio.feed(b"must not be heard")
    fixture.rec.release.set()
    fixture.listener.stop()
    assert fixture.texts == []
    assert fixture.rec.chunks == [b"before pause"]


def test_resume_uses_fresh_audio_and_resets_recognizer(listener_fixture):
    fixture = listener_fixture
    start(fixture)
    fixture.listener.pause()
    fixture.audio.feed(b"paused audio")
    assert fixture.listener.paused
    fixture.listener.resume()
    assert not fixture.listener.paused
    fixture.audio.feed(b"fresh audio")
    assert fixture.heard.wait(timeout=2)
    assert fixture.rec.chunks == [b"fresh audio"]
    assert fixture.rec.resets >= 1


def test_stop_is_bounded_and_blocks_late_transcription(listener_fixture):
    fixture = listener_fixture
    fixture.rec.release.clear()
    start(fixture)
    fixture.audio.feed()
    assert fixture.rec.accepted.wait(timeout=2)
    before = time.monotonic()
    fixture.listener.stop()
    assert time.monotonic() - before < 0.8
    assert not fixture.listener.active
    fixture.rec.release.set()
    assert fixture.audio.closed.wait(timeout=2)
    assert fixture.texts == []


def test_audio_queue_stays_bounded_and_drops_old_backlog(listener_fixture):
    fixture = listener_fixture
    fixture.rec.release.clear()
    start(fixture)
    fixture.audio.feed(b"in flight")
    assert fixture.rec.accepted.wait(timeout=2)
    for index in range(40):
        fixture.audio.feed(str(index).encode())
    assert fixture.listener._audio.qsize() <= 8
    fixture.listener.stop()
    fixture.rec.release.set()
    assert fixture.audio.closed.wait(timeout=2)
    assert fixture.texts == []


def test_empty_recognition_is_ignored(listener_fixture):
    fixture = listener_fixture
    fixture.rec.text = "  "
    start(fixture)
    fixture.audio.feed()
    assert fixture.rec.accepted.wait(timeout=2)
    fixture.listener.stop()
    assert fixture.texts == []


def test_long_utterance_is_finalized_without_waiting_forever(listener_fixture):
    fixture = listener_fixture
    fixture.rec.complete = False
    start(fixture)
    fixture.audio.feed(b"\x01\x00" * (16000 * 20))
    assert fixture.heard.wait(timeout=2)
    assert fixture.texts == ["phrase finale longue"]


def test_microphone_error_is_sanitized(listener_fixture, caplog):
    fixture = listener_fixture
    fixture.audio.query_error = RuntimeError("private audio or credential details")
    fixture.listener.start()
    assert fixture.failed.wait(timeout=2)
    assert "private" not in fixture.errors[0]
    assert "private" not in caplog.text
    assert not fixture.opened.is_set()


@pytest.mark.parametrize("sample_rate", [0, float("nan"), float("inf"), 1000000])
def test_invalid_microphone_format_has_useful_error(listener_fixture, sample_rate):
    fixture = listener_fixture
    fixture.audio.device["default_samplerate"] = sample_rate
    fixture.listener.start()
    assert fixture.failed.wait(timeout=2)
    assert "compatible" in fixture.errors[0]


def test_missing_model_never_opens_microphone(tmp_path):
    listener = LocalListener(tmp_path / "missing", Mock(), Mock(), Mock())
    with pytest.raises(SpeechError, match="Installer_Alicia"):
        listener.start()
    assert not listener.active


@pytest.mark.parametrize("device", [-1, True, "default"])
def test_invalid_device_is_rejected_without_opening_audio(listener_fixture, device):
    with pytest.raises(SpeechError, match="microphone"):
        listener_fixture.listener.start(device)
    assert listener_fixture.audio.callback is None


def test_repeated_start_does_not_open_multiple_streams(listener_fixture):
    fixture = listener_fixture
    start(fixture)
    fixture.listener.start()
    fixture.vosk.Model.assert_called_once()


def test_device_listing_excludes_outputs_and_does_not_record(monkeypatch):
    backend = SimpleNamespace(
        query_devices=Mock(
            return_value=[
                {"name": "Speakers", "max_input_channels": 0},
                {"name": "Microphone", "max_input_channels": 1},
            ]
        )
    )
    monkeypatch.setattr(listening, "_load_sounddevice", lambda: backend)
    assert list_input_devices() == [(1, "Microphone")]
    backend.query_devices.assert_called_once_with()


def test_device_listing_failure_never_exposes_native_details(monkeypatch):
    backend = SimpleNamespace(query_devices=Mock(side_effect=RuntimeError("private details")))
    monkeypatch.setattr(listening, "_load_sounddevice", lambda: backend)
    with pytest.raises(SpeechError) as error:
        list_input_devices()
    assert "private" not in str(error.value)


@pytest.mark.parametrize("payload", ["{}", '{"text": 1}', "[]", "not json"])
def test_malformed_recognition_is_not_a_question(payload):
    assert listening._recognized_text(payload, "text") == ""
