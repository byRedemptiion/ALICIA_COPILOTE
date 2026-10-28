"""Standalone worker run by the isolated Chatterbox Python, never by Qt.

Only bounded JSON lines travel over the pipes. Speech text is not passed on a
command line or written to disk. Package diagnostics go to the parent's DEVNULL.
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import wave
from pathlib import Path

MAX_TEXT = 4096
MAX_AUDIO_SECONDS = 300
MAX_CHUNK_CHARACTERS = 400


def speech_chunks(text: str) -> list[str]:
    """Keep each generation below the model's fixed 1000 speech-token limit."""
    remaining = " ".join(text.split())
    chunks = []
    while len(remaining) > MAX_CHUNK_CHARACTERS:
        end = MAX_CHUNK_CHARACTERS + 1
        boundary = max(remaining.rfind(mark, 0, end) for mark in (". ", "? ", "! "))
        if boundary >= 80:
            boundary += 1
        else:
            boundary = remaining.rfind(" ", 0, end)
            if boundary <= 0:
                boundary = MAX_CHUNK_CHARACTERS
        chunks.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def install_french_tokenizer(multilingual_module) -> None:
    """Avoid unrelated Chinese segmentation downloads in stock Chatterbox 0.1.7.

    Its multilingual tokenizer eagerly prepares Chinese assets even for French.
    Alicia uses French only. Keep its French normalization/encoding methods, but
    construct only the retained JSON tokenizer and refuse every other language.
    This adapter changes this disposable worker's class reference, never files.
    """
    from tokenizers import Tokenizer

    original = multilingual_module.MTLTokenizer

    class FrenchOnlyTokenizer(original):
        def __init__(self, vocab_file_path):
            self.tokenizer = Tokenizer.from_file(str(vocab_file_path))
            self.cangjie_converter = None
            self.check_vocabset_sot_eot()

        def encode(self, txt, language_id=None, lowercase=True, nfkd_normalize=True):
            if language_id != "fr":
                raise ValueError("This local tokenizer supports French only")
            return super().encode(
                txt,
                language_id=language_id,
                lowercase=lowercase,
                nfkd_normalize=nfkd_normalize,
            )

    multilingual_module.MTLTokenizer = FrenchOnlyTokenizer


def wav_bytes(samples, sample_rate: int) -> bytes:
    import numpy as np

    samples = np.asarray(samples)
    if samples.ndim == 2 and samples.shape[0] == 1:
        samples = samples[0]
    if (
        isinstance(sample_rate, bool)
        or not isinstance(sample_rate, int)
        or not 8000 <= sample_rate <= 96000
        or samples.ndim != 1
        or not 0 < samples.size <= sample_rate * MAX_AUDIO_SECONDS
        or not np.isfinite(samples).all()
    ):
        raise ValueError("Invalid audio")
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm)
    return output.getvalue()


def load_model(directory: Path, reference: Path, device: str, exaggeration: float):
    import torch
    from chatterbox import mtl_tts

    install_french_tokenizer(mtl_tts)
    ChatterboxMultilingualTTS = mtl_tts.ChatterboxMultilingualTTS
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    chosen = "cuda" if device == "auto" and torch.cuda.is_available() else device
    if chosen == "auto":
        chosen = "cpu"
    try:
        model = ChatterboxMultilingualTTS.from_local(str(directory), device=chosen)
        model.prepare_conditionals(str(reference), exaggeration=exaggeration)
    except RuntimeError:
        if device != "auto" or chosen != "cuda":
            raise
        # Automatic mode may recover from an unsupported CUDA driver or VRAM shortage.
        import gc

        gc.collect()
        torch.cuda.empty_cache()
        model = ChatterboxMultilingualTTS.from_local(str(directory), device="cpu")
        model.prepare_conditionals(str(reference), exaggeration=exaggeration)
    return model


def synthesize_reply(model, text: str, exaggeration: float, cfg_weight: float) -> bytes:
    import numpy as np

    segments, total = [], 0
    chunks = speech_chunks(text)
    for index, chunk in enumerate(chunks):
        generated = model.generate(
            chunk,
            language_id="fr",
            exaggeration=exaggeration,
            cfg_weight=cfg_weight,
            temperature=0.65,
        )
        samples = np.asarray(generated.detach().cpu().numpy())
        if samples.ndim == 2 and samples.shape[0] == 1:
            samples = samples[0]
        if samples.ndim != 1 or not samples.size or not np.isfinite(samples).all():
            raise ValueError("Invalid audio")
        total += samples.size
        if total > model.sr * MAX_AUDIO_SECONDS:
            raise ValueError("Speech duration exceeded")
        segments.append(samples)
        if index < len(chunks) - 1:
            pause = np.zeros(int(model.sr * 0.12), dtype=np.float32)
            total += pause.size
            if total > model.sr * MAX_AUDIO_SECONDS:
                raise ValueError("Speech duration exceeded")
            segments.append(pause)
    return wav_bytes(np.concatenate(segments), model.sr)


def main() -> int:
    protocol = sys.stdout
    # Third-party print/log calls must never corrupt the private pipe protocol.
    sys.stdout = sys.stderr
    try:
        directory, reference, device = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
        exaggeration, cfg_weight = float(sys.argv[4]), float(sys.argv[5])
        model = load_model(directory, reference, device, exaggeration)
        protocol.write('{"ready":true}\n')
        protocol.flush()
        while True:
            line = sys.stdin.readline(20000)
            if not line:
                return 0
            request = json.loads(line)
            text = request.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
                raise ValueError("Invalid text")
            content = synthesize_reply(model, text.strip(), exaggeration, cfg_weight)
            protocol.write(json.dumps({"wav": base64.b64encode(content).decode("ascii")}) + "\n")
            protocol.flush()
    except Exception:
        # Provider errors are deliberately generic: model exceptions may contain text.
        protocol.write('{"error":"speech_unavailable"}\n')
        protocol.flush()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
