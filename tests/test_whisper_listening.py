import array
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from alicia.audio import whisper_listening as module
from alicia.audio.ports import SpeechError
from alicia.audio.whisper_listening import WhisperListener, _PhraseBuffer, _rms, _transcribe


def pcm(amplitude=0, seconds=0.05, rate=16000):
    return array.array("h", [round(amplitude * 32767)] * round(rate * seconds)).tobytes()


def model_files(path):
    path.mkdir(parents=True, exist_ok=True)
    for name in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt"):
        (path / name).write_bytes(b"model fixture")


def wait_until(condition, seconds=3):
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "Listener did not reach the expected state"
        time.sleep(0.005)


class FakeSoundDevice:
    def __init__(self, rate=16000):
        self.rate = rate
        self.stream_arguments = None
        self.opened = threading.Event()
        self.closed = threading.Event()

    def query_devices(self, index, kind):
        assert kind == "input"
        return {"default_samplerate": self.rate, "max_input_channels": 1}

    def RawInputStream(self, **arguments):
        self.stream_arguments = arguments
        device = self

        class Stream:
            def __enter__(self):
                device.opened.set()
                return self

            def __exit__(self, *_args):
                device.closed.set()

        return Stream()

    def push(self, data):
        self.stream_arguments["callback"](data, len(data) // 2, None, None)


@pytest.fixture
def listener(tmp_path):
    model_files(tmp_path)
    device = FakeSoundDevice()
    engine = object()
    factory = Mock(return_value=engine)
    texts, errors, activity = [], [], []
    instance = WhisperListener(
        tmp_path, texts.append, errors.append, activity.append, backend=(factory, device)
    )
    yield SimpleNamespace(
        listener=instance,
        texts=texts,
        errors=errors,
        activity=activity,
        device=device,
        factory=factory,
        engine=engine,
    )
    instance.stop()


def test_silence_and_short_clicks_never_form_a_phrase():
    buffer = _PhraseBuffer(16000)
    for _ in range(30):
        assert buffer.push(pcm()) is None
    assert buffer.push(pcm(0.2)) is None
    assert all(buffer.push(pcm()) is None for _ in range(20))


def test_phrase_finishes_after_silence_and_keeps_pre_roll():
    buffer = _PhraseBuffer(16000)
    for _ in range(5):
        assert buffer.push(pcm()) is None
    for _ in range(8):
        assert buffer.push(pcm(0.2)) is None
    results = [buffer.push(pcm()) for _ in range(15)]
    phrases = [value for value in results if value is not None]
    assert len(phrases) == 1
    assert len(phrases[0]) >= len(pcm(seconds=1.1))


def test_long_speech_is_bounded():
    buffer = _PhraseBuffer(16000)
    result = None
    for _ in range(250):
        result = buffer.push(pcm(0.2))
        if result is not None:
            break
    assert result is not None
    assert len(result) <= 16000 * 12 * 2


def test_reset_discards_incomplete_phrase():
    buffer = _PhraseBuffer(16000)
    for _ in range(8):
        buffer.push(pcm(0.2))
    buffer.reset()
    assert all(buffer.push(pcm()) is None for _ in range(20))


def test_rms_is_normalized_without_numpy():
    assert _rms(pcm()) == 0
    assert _rms(pcm(0.5)) == pytest.approx(0.5, abs=0.001)
    assert _rms(b"x") == 0


def test_engine_is_local_french_and_filters_unreliable_segments(monkeypatch):
    sample_array = object()
    monkeypatch.setattr(module, "_resample_audio", lambda *_: sample_array)
    segments = [
        SimpleNamespace(text=" Alicia,", avg_logprob=-0.2, no_speech_prob=0.05),
        SimpleNamespace(text="compare ces objets.", avg_logprob=-0.4, no_speech_prob=0.1),
        SimpleNamespace(text="hallucination", avg_logprob=-2, no_speech_prob=0.1),
        SimpleNamespace(text="silence", avg_logprob=-0.1, no_speech_prob=0.99),
        SimpleNamespace(text="invalid", avg_logprob=float("nan"), no_speech_prob=0),
    ]
    engine = SimpleNamespace(transcribe=Mock(return_value=(iter(segments), object())))
    assert _transcribe(engine, b"audio", 48000) == "Alicia, compare ces objets."
    arguments = engine.transcribe.call_args.kwargs
    assert arguments["language"] == "fr"
    assert arguments["vad_filter"] is True
    assert arguments["beam_size"] == 5
    assert arguments["condition_on_previous_text"] is False
    assert "Alicia" in arguments["initial_prompt"]


def test_start_requires_complete_local_model(tmp_path):
    instance = WhisperListener(tmp_path, Mock(), Mock(), Mock())
    with pytest.raises(SpeechError, match="modèle Whisper"):
        instance.start()
    assert not instance.active


@pytest.mark.parametrize("device", ["auto", "remote", ""])
def test_unknown_compute_device_is_rejected(tmp_path, device):
    with pytest.raises(SpeechError):
        WhisperListener(tmp_path, Mock(), Mock(), Mock(), device=device)


def test_start_initializes_offline_cpu_model_without_network(listener):
    fixture = listener
    fixture.listener.start()
    assert fixture.device.opened.wait(2)
    fixture.factory.assert_called_once()
    options = fixture.factory.call_args.kwargs
    assert options["device"] == "cpu"
    assert options["compute_type"] == "int8"
    assert options["local_files_only"] is True
    wait_until(lambda: fixture.activity == [True])


def test_capture_uses_devices_actual_sample_rate(listener):
    fixture = listener
    fixture.device.rate = 48000
    fixture.listener.start()
    assert fixture.device.opened.wait(2)
    assert fixture.device.stream_arguments["samplerate"] == 48000
    assert fixture.device.stream_arguments["dtype"] == "int16"
    assert fixture.device.stream_arguments["channels"] == 1


def push_phrase(device):
    for _ in range(8):
        device.push(pcm(0.2))
        time.sleep(0.003)
    for _ in range(15):
        device.push(pcm())
        time.sleep(0.003)


def test_final_phrase_is_delivered_once_not_approximate_partials(listener, monkeypatch):
    fixture = listener
    transcribe = Mock(return_value="Alicia, compare ces objets.")
    monkeypatch.setattr(module, "_transcribe", transcribe)
    partials = []
    fixture.listener.on_partial = partials.append
    fixture.listener.start()
    assert fixture.device.opened.wait(2)
    push_phrase(fixture.device)
    wait_until(lambda: bool(fixture.texts))
    assert fixture.texts == ["Alicia, compare ces objets."]
    assert transcribe.call_count == 1
    assert partials == []


def test_pause_during_inference_discards_late_text(listener, monkeypatch):
    fixture = listener
    started, release = threading.Event(), threading.Event()

    def transcribe(*_args):
        started.set()
        assert release.wait(3)
        return "Alicia, ancien résultat"

    monkeypatch.setattr(module, "_transcribe", transcribe)
    fixture.listener.start()
    assert fixture.device.opened.wait(2)
    push_phrase(fixture.device)
    assert started.wait(2)
    fixture.listener.pause()
    release.set()
    wait_until(lambda: not fixture.listener._decoding.is_set())
    assert fixture.texts == []
    assert fixture.listener.paused


def test_stop_during_inference_is_bounded_and_discards_late_text(listener, monkeypatch):
    fixture = listener
    started, release = threading.Event(), threading.Event()

    def transcribe(*_args):
        started.set()
        assert release.wait(3)
        return "Alicia, ancien résultat"

    monkeypatch.setattr(module, "_transcribe", transcribe)
    fixture.listener.start()
    assert fixture.device.opened.wait(2)
    push_phrase(fixture.device)
    assert started.wait(2)
    before = time.monotonic()
    fixture.listener.stop()
    assert time.monotonic() - before < 0.4
    release.set()
    assert fixture.device.closed.wait(2)
    assert fixture.texts == []
    assert not fixture.listener.active


def test_audio_during_decode_is_discarded_without_invalidating_current_result(listener):
    fixture = listener
    instance = fixture.listener
    instance._running = True
    instance._decoding.set()
    before = instance._epoch
    instance._put_audio(instance._generation, pcm(0.2), None)
    assert instance._audio.empty()
    assert instance._epoch == before


def test_load_failure_is_sanitized(listener):
    fixture = listener
    fixture.factory.side_effect = RuntimeError("private environment details")
    fixture.listener.start()
    wait_until(lambda: bool(fixture.errors))
    assert "private" not in fixture.errors[0]
    assert not fixture.listener.active


def test_resampling_48khz_preserves_length_and_normalization():
    samples = module._resample_audio(pcm(0.2, seconds=0.3, rate=48000), 48000)
    assert len(samples) == 4800
    assert str(samples.dtype) == "float32"
    assert abs(float(samples.mean()) - 0.2) < 0.005
