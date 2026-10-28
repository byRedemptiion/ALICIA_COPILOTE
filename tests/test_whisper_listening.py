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
        tmp_path,
        texts.append,
        errors.append,
        activity.append,
        backend=(factory, device),
        device="cpu",
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
    for _ in range(450):
        result = buffer.push(pcm(0.2))
        if result is not None:
            break
    assert result is not None
    assert len(result) <= 16000 * 20 * 2


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
    ]
    engine = SimpleNamespace(transcribe=Mock(return_value=(iter(segments), object())))
    assert _transcribe(engine, b"audio", 48000) == "Alicia, compare ces objets."
    arguments = engine.transcribe.call_args.kwargs
    assert arguments["language"] == "fr"
    assert arguments["vad_filter"] is True
    assert arguments["beam_size"] == 5
    assert arguments["temperature"] == 0.0
    assert arguments["word_timestamps"] is True
    assert arguments["condition_on_previous_text"] is False
    assert "Alicia" in arguments["initial_prompt"]


def test_start_requires_complete_local_model(tmp_path):
    instance = WhisperListener(tmp_path, Mock(), Mock(), Mock())
    with pytest.raises(SpeechError, match="modèle Whisper"):
        instance.start()
    assert not instance.active


@pytest.mark.parametrize("device", ["metal", "remote", ""])
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


def test_audio_during_decode_is_kept_without_invalidating_current_result(listener):
    fixture = listener
    instance = fixture.listener
    instance._running = True
    instance._decoding.set()
    before = instance._epoch
    instance._put_audio(instance._generation, pcm(0.2), None)
    assert instance._audio.get_nowait() == (before, pcm(0.2))
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


@pytest.mark.parametrize(
    "unreliable",
    [
        {"avg_logprob": -1.2},
        {"avg_logprob": float("nan")},
        {"no_speech_prob": 0.9},
        {"no_speech_prob": "invalid"},
        {"compression_ratio": 3.5},
        {"words": [SimpleNamespace(probability=0.2), SimpleNamespace(probability=0.3)]},
        {"words": [SimpleNamespace(probability=float("nan"))]},
    ],
)
def test_unreliable_segment_rejects_the_whole_request_instead_of_changing_its_meaning(
    monkeypatch, unreliable
):
    monkeypatch.setattr(module, "_resample_audio", lambda *_: object())
    middle = {"text": "ne vends pas", "avg_logprob": -0.2, "no_speech_prob": 0.05}
    middle.update(unreliable)
    segments = [
        SimpleNamespace(text="Alicia,", avg_logprob=-0.2, no_speech_prob=0.05),
        SimpleNamespace(**middle),
        SimpleNamespace(text="cet objet.", avg_logprob=-0.2, no_speech_prob=0.05),
    ]
    engine = SimpleNamespace(transcribe=Mock(return_value=(iter(segments), object())))
    assert _transcribe(engine, b"audio", 16000) == ""


def test_very_long_text_cannot_become_an_unbounded_request(monkeypatch):
    monkeypatch.setattr(module, "_resample_audio", lambda *_: object())
    segment = SimpleNamespace(text="texte " * 400, avg_logprob=-0.2, no_speech_prob=0.05)
    engine = SimpleNamespace(transcribe=Mock(return_value=(iter([segment]), object())))
    assert _transcribe(engine, b"audio", 16000) == ""


def test_auto_device_uses_cpu_without_a_local_cuda_device(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "_cuda_is_available", lambda: False)
    engine = object()
    factory = Mock(return_value=engine)
    assert module._create_engine(factory, tmp_path, "auto") is engine
    assert factory.call_count == 1
    assert factory.call_args.kwargs["device"] == "cpu"
    assert factory.call_args.kwargs["compute_type"] == "int8"
    assert factory.call_args.kwargs["local_files_only"] is True


def test_auto_device_probes_a_real_decode_before_accepting_cuda(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "_cuda_is_available", lambda: True)
    gpu = object()
    factory = Mock(return_value=gpu)
    probe = Mock()
    monkeypatch.setattr(module, "_probe_cuda_engine", probe)
    assert module._create_engine(factory, tmp_path, "auto") is gpu
    probe.assert_called_once_with(gpu)
    assert factory.call_args.kwargs["device"] == "cuda"
    assert factory.call_args.kwargs["compute_type"] == "float16"


def test_lazy_cuda_failure_falls_back_to_local_cpu_only(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "_cuda_is_available", lambda: True)
    gpu, cpu = object(), object()
    factory = Mock(side_effect=[gpu, cpu])
    monkeypatch.setattr(
        module, "_probe_cuda_engine", Mock(side_effect=RuntimeError("missing cuDNN"))
    )
    assert module._create_engine(factory, tmp_path, "auto") is cpu
    assert [call.kwargs["device"] for call in factory.call_args_list] == ["cuda", "cpu"]
    assert all(call.kwargs["local_files_only"] for call in factory.call_args_list)


def test_explicit_cuda_failure_is_not_silently_replaced(tmp_path):
    factory = Mock(side_effect=RuntimeError("missing cuDNN"))
    with pytest.raises(RuntimeError):
        module._create_engine(factory, tmp_path, "cuda")
    assert factory.call_count == 1


def test_cuda_probe_consumes_the_lazy_inference_generator():
    decoded = []

    def segments():
        decoded.append(True)
        yield object()

    engine = SimpleNamespace(transcribe=Mock(return_value=(segments(), object())))
    module._probe_cuda_engine(engine)
    assert decoded == [True]
    options = engine.transcribe.call_args.kwargs
    assert options["vad_filter"] is False
    assert options["language"] == "fr"


def test_question_audio_is_preserved_while_wakeword_is_decoding(listener, monkeypatch):
    fixture = listener
    started, release = threading.Event(), threading.Event()
    calls = []

    def transcribe(*_args):
        calls.append(True)
        if len(calls) == 1:
            started.set()
            assert release.wait(3)
            return "Alicia"
        return "Compare ces objets."

    monkeypatch.setattr(module, "_transcribe", transcribe)
    fixture.listener.start()
    assert fixture.device.opened.wait(2)
    push_phrase(fixture.device)
    assert started.wait(2)
    push_phrase(fixture.device)
    release.set()
    wait_until(lambda: len(fixture.texts) == 2)
    assert fixture.texts == ["Alicia", "Compare ces objets."]


def test_interruption_mode_invalidates_pending_audio_without_resuming(listener):
    instance = listener.listener
    instance.pause()
    before = instance._epoch
    instance._audio.put_nowait((before, pcm(0.2)))
    instance.set_interruption_mode(True)
    assert instance._epoch > before
    assert instance._audio.empty()
    assert instance.paused
    assert instance._interruption_mode
    instance.set_interruption_mode(False)
    assert not instance._interruption_mode
    assert instance.paused


def test_interruption_uses_short_endpoint_and_its_dedicated_decoder(listener, monkeypatch):
    fixture = listener
    regular = Mock(return_value="ordinary")
    interruption = Mock(return_value="Alicia stop")
    monkeypatch.setattr(module, "_transcribe", regular)
    monkeypatch.setattr(module, "_transcribe_interruption", interruption)
    fixture.listener.set_interruption_mode(True)
    fixture.listener.start()
    assert fixture.device.opened.wait(2)
    for _ in range(4):
        fixture.device.push(pcm(0.2))
        time.sleep(0.003)
    for _ in range(8):
        fixture.device.push(pcm())
        time.sleep(0.003)
    wait_until(lambda: bool(fixture.texts))
    assert fixture.texts == ["Alicia stop"]
    regular.assert_not_called()
    interruption.assert_called_once()


def test_mode_switch_during_inference_discards_late_command(listener, monkeypatch):
    fixture = listener
    started, release = threading.Event(), threading.Event()

    def transcribe(*_args):
        started.set()
        assert release.wait(3)
        return "ancienne question"

    monkeypatch.setattr(module, "_transcribe", transcribe)
    fixture.listener.start()
    assert fixture.device.opened.wait(2)
    push_phrase(fixture.device)
    assert started.wait(2)
    fixture.listener.set_interruption_mode(True)
    release.set()
    wait_until(lambda: not fixture.listener._decoding.is_set())
    assert fixture.texts == []
