"""Explicit preparation of the speech model; inference always remains offline."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from alicia.audio.ports import SpeechError

# The upstream faster-whisper registry maps both "turbo" and "large-v3-turbo"
# to this conversion of OpenAI's multilingual model. English-only distil models
# are unsuitable for the French microphone used by Alicia.
WHISPER_REPOSITORY = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
WHISPER_FILES = ("config.json", "model.bin", "tokenizer.json")
WHISPER_PATTERNS = (*WHISPER_FILES, "preprocessor_config.json", "vocabulary.*", "README.md")
MAX_MODEL_BYTES = 3 * 1024 * 1024 * 1024


def whisper_model_is_present(path: Path) -> bool:
    def complete_file(name: str) -> bool:
        candidate = path / name
        try:
            return (
                not candidate.is_symlink() and candidate.is_file() and candidate.stat().st_size > 0
            )
        except OSError:
            return False

    return (
        not path.is_symlink()
        and all(complete_file(name) for name in WHISPER_FILES)
        and any(complete_file(name) for name in ("vocabulary.txt", "vocabulary.json"))
    )


def prepare_whisper_model(target: Path, downloader=None) -> Path:
    """Download model files through the supported Hugging Face client once.

    Transport TLS and the client's artifact verification remain enabled. Recorded
    SHA256 values are local provenance, not a separate publisher signature.
    """
    target = Path(target)
    if target.is_symlink():
        raise SpeechError("Le dossier Whisper est un lien symbolique ; son contenu est préservé.")
    if whisper_model_is_present(target):
        return target
    if target.exists():
        raise SpeechError(
            "Le dossier Whisper existe mais est incomplet. Déplacez-le avant de relancer l’installation."
        )
    if downloader is None:
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            raise SpeechError(
                "Le téléchargement Whisper est indisponible. Relancez l’installation des dépendances."
            ) from None
        downloader = snapshot_download
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="alicia-whisper-", dir=target.parent) as temp:
            staging = Path(temp) / "model"
            downloader(
                repo_id=WHISPER_REPOSITORY,
                local_dir=str(staging),
                allow_patterns=list(WHISPER_PATTERNS),
                max_workers=2,
            )
            if staging.is_symlink() or any(path.is_symlink() for path in staging.iterdir()):
                raise SpeechError("Le téléchargement Whisper contient un fichier invalide.")
            if not whisper_model_is_present(staging):
                raise SpeechError(
                    "Le téléchargement Whisper ne contient pas tous les fichiers attendus."
                )
            total = 0
            hashes = {}
            for path in staging.iterdir():
                if path.name == ".cache":
                    continue
                if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
                    raise SpeechError("Le téléchargement Whisper contient un fichier invalide.")
                total += path.stat().st_size
                if total > MAX_MODEL_BYTES:
                    raise SpeechError("Le modèle Whisper dépasse la taille attendue.")
                with path.open("rb") as source:
                    hashes[path.name] = hashlib.file_digest(source, "sha256").hexdigest()
            cache = staging / ".cache"
            if cache.exists():
                shutil.rmtree(cache)
            (staging / ".alicia-model.json").write_text(
                json.dumps(
                    {
                        "repository": WHISPER_REPOSITORY,
                        "downloaded_at": datetime.now(UTC).isoformat(),
                        "sha256": hashes,
                        "integrity": "Transport éditeur vérifié ; empreintes locales, pas de signature indépendante",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            os.rename(staging, target)
            return target
    except SpeechError:
        raise
    except Exception:
        raise SpeechError(
            "Préparation de Whisper impossible. Vérifiez Internet, l’espace disque et relancez Installer_Alicia.bat."
        ) from None
