from types import SimpleNamespace

import pytest

from alicia.audio.openai_speech import (
    OpenAISpeechProvider,
    SpeechError,
    SpeechSettings,
)

WAV = b"RIFF\x04\x00\x00\x00WAVE"


def test_settings_repr_never_exposes_api_key():
    settings = SpeechSettings(api_key="private-value")
    assert "private-value" not in repr(settings)
    assert "api_key" not in repr(settings)


class FakeSpeech:
    def __init__(self, chunks=(WAV,), error=None):
        self.chunks = chunks
        self.error = error
        self.calls = []
        self.closed = False

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def iter_bytes(self):
        yield from self.chunks


def provider(fake, **settings):
    client = SimpleNamespace(
        audio=SimpleNamespace(speech=SimpleNamespace(with_streaming_response=fake))
    )
    return OpenAISpeechProvider(SpeechSettings(api_key="test-key", **settings), client)


def test_speech_requests_soft_voice_and_streams_wav():
    fake = FakeSpeech((WAV[:5], WAV[5:]))
    audio = provider(fake).synthesize("Voici mon conseil.")
    assert audio == WAV
    assert len(fake.calls) == 1
    request = fake.calls[0]
    assert request["model"] == "gpt-4o-mini-tts"
    assert request["voice"] == "shimmer"
    assert request["response_format"] == "wav"
    assert request["input"] == "Voici mon conseil."
    assert "féminine douce" in request["instructions"]
    assert fake.closed


@pytest.mark.parametrize("model", ["tts-1", "tts-1-hd"])
def test_older_models_omit_unsupported_instructions(model):
    fake = FakeSpeech()
    provider(fake, model=model, voice="nova").synthesize("Bonjour.")
    assert "instructions" not in fake.calls[0]
    assert fake.calls[0]["voice"] == "nova"


def test_dated_mini_tts_supports_instructions():
    fake = FakeSpeech()
    provider(fake, model="gpt-4o-mini-tts-2025-12-15").synthesize("Bonjour.")
    assert "instructions" in fake.calls[0]


@pytest.mark.parametrize("text", ["", "   ", "a" * 4097])
def test_invalid_text_does_not_call_api(text):
    fake = FakeSpeech()
    with pytest.raises(SpeechError):
        provider(fake).synthesize(text)
    assert fake.calls == []


def test_missing_key_fails_before_client_initialization(monkeypatch):
    def forbidden_client(**kwargs):
        pytest.fail("No API client should be initialized without a key")

    monkeypatch.setattr("alicia.audio.openai_speech.OpenAI", forbidden_client)
    with pytest.raises(SpeechError, match="OPENAI_API_KEY"):
        OpenAISpeechProvider(SpeechSettings(api_key=None)).synthesize("Bonjour.")


def test_client_uses_bounded_timeout_and_no_retries(monkeypatch):
    fake = FakeSpeech()
    captured = {}

    def make_client(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            audio=SimpleNamespace(speech=SimpleNamespace(with_streaming_response=fake))
        )

    monkeypatch.setattr("alicia.audio.openai_speech.OpenAI", make_client)
    OpenAISpeechProvider(SpeechSettings(api_key="test-key", timeout_seconds=12)).synthesize(
        "Bonjour."
    )
    assert captured["timeout"] == 12
    assert captured["max_retries"] == 0


def test_api_error_is_sanitized_and_not_retried():
    fake = FakeSpeech(error=RuntimeError("secret-key confidential question"))
    with pytest.raises(SpeechError) as failure:
        provider(fake).synthesize("Private text")
    assert "secret-key" not in str(failure.value)
    assert "confidential" not in str(failure.value)
    assert "Private text" not in str(failure.value)
    assert len(fake.calls) == 1


@pytest.mark.parametrize("audio", [b"", b"not a wav file"])
def test_empty_or_invalid_audio_is_rejected(audio):
    fake = FakeSpeech((audio,))
    with pytest.raises(SpeechError, match="WAV"):
        provider(fake).synthesize("Bonjour.")
    assert fake.closed
