import base64
import io
import json
import subprocess
import sys
import threading
import wave
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from alicia.audio import chatterbox_speech as speech
from alicia.audio.chatterbox_speech import ChatterboxSpeechProvider, ChatterboxSpeechSettings
from alicia.audio.chatterbox_worker import wav_bytes
from alicia.audio.ports import SpeechError


def settings(tmp_path, **kwargs):
    return ChatterboxSpeechSettings(tmp_path / "runtime", tmp_path / "model", **kwargs)


def sample_wav():
    return wav_bytes([0.0, 0.5, -0.5], 24000)


def fake_worker(tmp_path, payload=None, *, hang=False):
    path = tmp_path / "fake-worker.py"
    payload = payload or {"wav": base64.b64encode(sample_wav()).decode("ascii")}
    path.write_text(
        "import sys,json,os,time\n"
        "assert os.environ['HF_HUB_OFFLINE']=='1'\n"
        "assert os.environ['TRANSFORMERS_OFFLINE']=='1'\n"
        "print('{\"ready\":true}',flush=True)\n"
        "for line in sys.stdin:\n"
        " request=json.loads(line)\n"
        " assert 'text' in request\n"
        + (" time.sleep(30)\n" if hang else "")
        + " print("
        + repr(json.dumps(payload))
        + ",flush=True)\n"
    )
    return [sys.executable, "-u", str(path)]


def provider_with_fake(tmp_path, monkeypatch, **kwargs):
    provider = ChatterboxSpeechProvider(settings(tmp_path))
    command = fake_worker(tmp_path, **kwargs)
    monkeypatch.setattr(provider, "_validate_installation", lambda: None)
    monkeypatch.setattr(provider, "_command", lambda: command)
    return provider


def test_real_pipe_protocol_reuses_worker_and_never_passes_text_as_argument(tmp_path, monkeypatch):
    provider = provider_with_fake(tmp_path, monkeypatch)
    real_popen, calls = subprocess.Popen, []

    def spawn(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return real_popen(arguments, **kwargs)

    monkeypatch.setattr(speech.subprocess, "Popen", spawn)
    try:
        assert provider.synthesize("question privée un") == sample_wav()
        assert provider.synthesize("question privée deux") == sample_wav()
        assert len(calls) == 1
        assert "privée" not in repr(calls[0][0])
        assert calls[0][1]["stderr"] is subprocess.DEVNULL
        assert calls[0][1]["env"]["HF_HUB_DISABLE_TELEMETRY"] == "1"
    finally:
        provider.close()


def test_missing_model_fails_explicitly_without_downloading(tmp_path):
    with pytest.raises(SpeechError, match="Installer_Alicia"):
        ChatterboxSpeechProvider(settings(tmp_path)).synthesize("Bonjour.")


@pytest.mark.parametrize("text", [None, "", "  ", "x" * 4097])
def test_invalid_text_is_rejected_before_start(tmp_path, monkeypatch, text):
    provider = ChatterboxSpeechProvider(settings(tmp_path))
    monkeypatch.setattr(provider, "_start", lambda *args: pytest.fail("must stay lazy"))
    with pytest.raises(SpeechError):
        provider.synthesize(text)


@pytest.mark.parametrize(
    "kwargs",
    [{"device": "bad"}, {"cfg_weight": float("nan")}, {"exaggeration": 2}, {"cfg_weight": True}],
)
def test_invalid_settings_are_rejected(tmp_path, kwargs):
    with pytest.raises(SpeechError):
        ChatterboxSpeechProvider(settings(tmp_path, **kwargs))


@pytest.mark.parametrize("payload", [{"wav": "bad!"}, {"wav": ""}, {"error": "private text"}])
def test_bad_worker_response_is_sanitized_and_worker_stopped(tmp_path, monkeypatch, payload):
    provider = provider_with_fake(tmp_path, monkeypatch, payload=payload)
    with pytest.raises(SpeechError) as error:
        provider.synthesize("private text")
    assert "private" not in str(error.value)
    assert provider._process is None


def test_worker_timeout_is_bounded_and_stops_process(tmp_path, monkeypatch):
    provider = provider_with_fake(tmp_path, monkeypatch, hang=True)
    monkeypatch.setattr(speech, "WORKER_TIMEOUT_SECONDS", 0.2)
    with pytest.raises(SpeechError, match="délai"):
        provider.synthesize("Bonjour.")
    assert provider._process is None


def test_close_interrupts_synthesis_without_waiting_for_its_lock(tmp_path, monkeypatch):
    provider = provider_with_fake(tmp_path, monkeypatch, hang=True)
    started = threading.Event()
    original_start = provider._start

    def start(generation, deadline):
        result = original_start(generation, deadline)
        started.set()
        return result

    monkeypatch.setattr(provider, "_start", start)
    errors = []

    def synthesize():
        try:
            provider.synthesize("Bonjour.")
        except SpeechError as error:
            errors.append(error)

    thread = threading.Thread(target=synthesize)
    thread.start()
    assert started.wait(2)
    provider.close()
    thread.join(2)
    assert not thread.is_alive()
    assert errors
    assert provider._process is None


def test_stop_during_slow_validation_cannot_start_worker_afterwards(tmp_path, monkeypatch):
    provider = ChatterboxSpeechProvider(settings(tmp_path))

    def validate():
        provider.close()

    monkeypatch.setattr(provider, "_validate_installation", validate)
    monkeypatch.setattr(
        speech.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("stale start")
    )
    with pytest.raises(SpeechError, match="arrêtée"):
        provider.synthesize("Bonjour.")
    assert provider._process is None


def test_worker_pcm_conversion_returns_valid_mono_wav():
    with wave.open(io.BytesIO(sample_wav()), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 24000
        assert audio.getnframes() == 3


def test_real_worker_loop_uses_french_and_prepared_expression(tmp_path, monkeypatch):
    from alicia.audio import chatterbox_worker as worker

    tensor = SimpleNamespace()
    tensor.detach = lambda: tensor
    tensor.cpu = lambda: tensor
    tensor.numpy = lambda: [[0.0, 0.5, -0.5]]
    model = SimpleNamespace(generate=Mock(return_value=tensor), sr=24000)
    loader = Mock(return_value=model)
    output = io.StringIO()
    monkeypatch.setattr(worker, "load_model", loader)
    monkeypatch.setattr(sys, "argv", ["worker", str(tmp_path), "reference.wav", "cpu", ".35", ".5"])
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"text":"Bonjour Alicia."}\n'))
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    assert worker.main() == 0
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert records[0] == {"ready": True}
    assert base64.b64decode(records[1]["wav"]) == sample_wav()
    model.generate.assert_called_once_with(
        "Bonjour Alicia.", language_id="fr", exaggeration=0.35, cfg_weight=0.5, temperature=0.65
    )
    loader.assert_called_once_with(tmp_path, speech.Path("reference.wav"), "cpu", 0.35)


def test_automatic_cuda_failure_recovers_locally_on_cpu(tmp_path, monkeypatch):
    from alicia.audio import chatterbox_worker as worker

    torch = SimpleNamespace(
        set_num_threads=Mock(),
        cuda=SimpleNamespace(is_available=lambda: True, empty_cache=Mock()),
    )
    model = SimpleNamespace(prepare_conditionals=Mock())
    local_loader = Mock(side_effect=[RuntimeError("out of memory"), model])
    monkeypatch.setitem(sys.modules, "torch", torch)
    multilingual = SimpleNamespace(
        ChatterboxMultilingualTTS=SimpleNamespace(from_local=local_loader)
    )
    monkeypatch.setitem(sys.modules, "chatterbox", SimpleNamespace(mtl_tts=multilingual))
    adapter = Mock()
    monkeypatch.setattr(worker, "install_french_tokenizer", adapter)
    assert worker.load_model(tmp_path, tmp_path / "reference.wav", "auto", 0.35) is model
    adapter.assert_called_once_with(multilingual)
    assert [call.kwargs["device"] for call in local_loader.call_args_list] == ["cuda", "cpu"]
    model.prepare_conditionals.assert_called_once_with(
        str(tmp_path / "reference.wav"), exaggeration=0.35
    )


def test_french_adapter_skips_eager_chinese_setup_and_rejects_other_languages(tmp_path):
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel

    from alicia.audio.chatterbox_worker import install_french_tokenizer

    vocab = tmp_path / "vocab.json"
    Tokenizer(WordLevel({"[UNK]": 0, "[START]": 1, "[STOP]": 2}, unk_token="[UNK]")).save(
        str(vocab)
    )

    class Original:
        def __init__(self, path):
            pytest.fail("The stock constructor would download unrelated Chinese assets")

        def check_vocabset_sot_eot(self):
            assert "[START]" in self.tokenizer.get_vocab()
            assert "[STOP]" in self.tokenizer.get_vocab()

        def encode(self, txt, **kwargs):
            assert kwargs["language_id"] == "fr"
            return [42]

    module = SimpleNamespace(MTLTokenizer=Original)
    install_french_tokenizer(module)
    tokenizer = module.MTLTokenizer(vocab)
    assert tokenizer.cangjie_converter is None
    assert tokenizer.encode("Bonjour", language_id="fr") == [42]
    with pytest.raises(ValueError, match="French only"):
        tokenizer.encode("你好", language_id="zh")


def test_long_reply_is_split_at_sentences_without_dropping_text():
    from alicia.audio.chatterbox_worker import speech_chunks

    text = "La première phrase reste complète. " * 40
    chunks = speech_chunks(text)
    assert len(chunks) > 1
    assert " ".join(chunks) == text.strip()
    assert all(len(chunk) <= 400 for chunk in chunks)
    assert all(chunk.endswith(".") for chunk in chunks)


def test_extremely_long_word_is_split_without_exceeding_model_limit():
    from alicia.audio.chatterbox_worker import speech_chunks

    chunks = speech_chunks("a" * 1200)
    assert list(map(len, chunks)) == [400, 400, 400]


def test_multi_chunk_synthesis_reads_all_text_in_french_with_bounded_pauses():
    from alicia.audio.chatterbox_worker import speech_chunks, synthesize_reply

    tensor = SimpleNamespace()
    tensor.detach = lambda: tensor
    tensor.cpu = lambda: tensor
    tensor.numpy = lambda: [[0.0, 0.5, -0.5]]
    model = SimpleNamespace(generate=Mock(return_value=tensor), sr=8000)
    text = "C’est une phrase française, complète et naturelle. " * 25
    chunks = speech_chunks(text)
    content = synthesize_reply(model, text, 0.35, 0.5)
    assert [call.args[0] for call in model.generate.call_args_list] == chunks
    assert all(call.kwargs["language_id"] == "fr" for call in model.generate.call_args_list)
    assert " ".join(chunks) == text.strip()
    with wave.open(io.BytesIO(content), "rb") as audio:
        assert audio.getnframes() == len(chunks) * 3 + (len(chunks) - 1) * 960


@pytest.mark.parametrize(
    "samples,rate", [([], 24000), ([float("nan")], 24000), ([0], True), ([[[0]]], 24000)]
)
def test_worker_rejects_invalid_samples(samples, rate):
    with pytest.raises(ValueError):
        wav_bytes(samples, rate)
