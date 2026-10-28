"""Optional speech synthesis; playback belongs to the desktop interface."""

from .ports import SpeechError

__all__ = ["OpenAISpeechProvider", "SpeechError", "SpeechSettings"]


def __getattr__(name):
    if name in {"OpenAISpeechProvider", "SpeechSettings"}:
        from .openai_speech import OpenAISpeechProvider, SpeechSettings

        return {"OpenAISpeechProvider": OpenAISpeechProvider, "SpeechSettings": SpeechSettings}[
            name
        ]
    raise AttributeError(name)
