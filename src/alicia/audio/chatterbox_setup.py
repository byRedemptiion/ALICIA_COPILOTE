"""Explicit installation of the expressive voice in an isolated Python environment.

The Chatterbox dependency graph uses NumPy 1.x on Python 3.12. It must not be
installed into Alicia's NumPy 2 environment. All network work belongs here;
normal speech uses the retained files and an offline worker only.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import wave
from datetime import UTC, datetime
from pathlib import Path

from alicia.audio.ports import SpeechError

CHATTERBOX_VERSION = "0.1.7"
CHATTERBOX_REPOSITORY = "ResembleAI/chatterbox"
CHATTERBOX_FILES = (
    "ve.pt",
    "t3_mtl23ls_v2.safetensors",
    "s3gen.pt",
    "grapheme_mtl_merged_expanded_v1.json",
    "conds.pt",
    "Cangjie5_TC.json",
)
MAX_MODEL_BYTES = 4 * 1024 * 1024 * 1024
_MODEL_MANIFEST = ".alicia-expressive.json"
_RUNTIME_MANIFEST = ".alicia-expressive-runtime.json"


def runtime_python(directory: Path) -> Path:
    return Path(directory) / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _reference_is_valid(path: Path) -> bool:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
            return False
        with wave.open(str(path), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate()
            return (
                audio.getnchannels() == 1
                and audio.getsampwidth() == 2
                and 8000 <= audio.getframerate() <= 96000
                and 3 <= duration <= 20
            )
    except (OSError, EOFError, wave.Error, ZeroDivisionError):
        return False


def expressive_model_is_present(directory: Path) -> bool:
    """Check downloaded files against recorded local fingerprints, not a signature."""
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        return False
    try:
        manifest_path = directory / _MODEL_MANIFEST
        if manifest_path.is_symlink():
            return False
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["repository"] != CHATTERBOX_REPOSITORY:
            return False
        total = 0
        for name in (*CHATTERBOX_FILES, "reference.wav"):
            path = directory / name
            record = manifest["files"][name]
            if path.is_symlink() or not path.is_file():
                return False
            size = path.stat().st_size
            total += size
            if not 0 < size == record["size"] or _digest(path) != record["sha256"]:
                return False
        return total <= MAX_MODEL_BYTES and _reference_is_valid(directory / "reference.wav")
    except (OSError, ValueError, KeyError, TypeError):
        return False


def expressive_runtime_is_present(directory: Path) -> bool:
    directory = Path(directory)
    if directory.is_symlink():
        return False
    try:
        manifest = directory / _RUNTIME_MANIFEST
        return (
            not manifest.is_symlink()
            and json.loads(manifest.read_text(encoding="utf-8"))["chatterbox_version"]
            == CHATTERBOX_VERSION
            and runtime_python(directory).is_file()
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def chatterbox_voice_is_present(runtime_directory: Path, model_directory: Path) -> bool:
    return expressive_runtime_is_present(runtime_directory) and expressive_model_is_present(
        model_directory
    )


def _prepare_model(target: Path, reference_audio: Path, downloader) -> Path:
    if target.is_symlink():
        raise SpeechError("Le dossier de voix expressive est un lien symbolique ; il est conservé.")
    if expressive_model_is_present(target):
        return target
    if target.exists():
        raise SpeechError(
            "Le dossier de voix expressive existe mais est incomplet. Déplacez-le avant de relancer l’installation."
        )
    if not _reference_is_valid(reference_audio):
        raise SpeechError("L’extrait de référence féminin synthétique est absent ou invalide.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="alicia-expressive-", dir=target.parent) as temp:
        staging = Path(temp) / "model"
        downloader(
            repo_id=CHATTERBOX_REPOSITORY,
            revision="main",
            local_dir=str(staging),
            allow_patterns=list(CHATTERBOX_FILES),
            max_workers=2,
        )
        records = {}
        total = 0
        for name in CHATTERBOX_FILES:
            path = staging / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
                raise SpeechError("Le modèle de voix expressive téléchargé est incomplet.")
            size = path.stat().st_size
            total += size
            if total > MAX_MODEL_BYTES:
                raise SpeechError("Le modèle de voix expressive dépasse la taille autorisée.")
            records[name] = {"size": size, "sha256": _digest(path)}
        # This is an Alicia-generated synthetic female voice, not a person's recording.
        reference = staging / "reference.wav"
        shutil.copyfile(reference_audio, reference)
        records[reference.name] = {
            "size": reference.stat().st_size,
            "sha256": _digest(reference),
        }
        cache = staging / ".cache"
        if cache.exists():
            shutil.rmtree(cache)
        (staging / _MODEL_MANIFEST).write_text(
            json.dumps(
                {
                    "repository": CHATTERBOX_REPOSITORY,
                    "downloaded_at": datetime.now(UTC).isoformat(),
                    "files": records,
                    "reference": "Voix féminine synthétique Kokoro ff_siwis fournie avec Alicia",
                    "integrity": "Transport éditeur vérifié ; SHA256 locaux, sans signature indépendante",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        if target.exists() or target.is_symlink():
            raise SpeechError(
                "Le dossier vocal a été créé pendant l’installation ; il est conservé."
            )
        os.rename(staging, target)
    return target


def _run_install(arguments: list[str], runner, timeout: int) -> None:
    result = runner(
        arguments,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise SpeechError(
            "Installation du moteur expressif impossible. Vérifiez Internet, le disque et la compatibilité de Python."
        )


def _prepare_runtime(target: Path, runner, device: str) -> Path:
    if target.is_symlink():
        raise SpeechError(
            "Le dossier du moteur expressif est un lien symbolique ; il est conservé."
        )
    if expressive_runtime_is_present(target):
        return target
    if target.exists():
        raise SpeechError(
            "Le dossier du moteur expressif existe mais est incomplet. Déplacez-le avant de relancer l’installation."
        )
    uv = shutil.which("uv")
    if not uv:
        raise SpeechError(
            "uv est nécessaire pour isoler le moteur vocal. Relancez Installer_Alicia.bat."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    # A venv cannot be moved after creation: entry points contain absolute paths.
    target.mkdir()
    try:
        _run_install([uv, "venv", "--python", "3.12", str(target)], runner, 300)
        python = runtime_python(target)
        use_cuda = device == "cuda" or (device == "auto" and shutil.which("nvidia-smi"))
        # Official PyTorch wheel indexes avoid installing Linux CUDA libraries on
        # a CPU-only computer. Auto chooses CUDA only when its driver is present.
        torch_index = "https://download.pytorch.org/whl/" + ("cu124" if use_cuda else "cpu")
        _run_install(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                "--index-url",
                torch_index,
                "torch==2.6.0",
                "torchaudio==2.6.0",
            ],
            runner,
            1800,
        )
        _run_install(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                f"chatterbox-tts=={CHATTERBOX_VERSION}",
            ],
            runner,
            1800,
        )
        _run_install(
            [
                str(python),
                "-c",
                "from chatterbox.mtl_tts import ChatterboxMultilingualTTS; "
                "from importlib.metadata import version; "
                f"assert version('chatterbox-tts') == '{CHATTERBOX_VERSION}'",
            ],
            runner,
            120,
        )
        (target / _RUNTIME_MANIFEST).write_text(
            json.dumps({"chatterbox_version": CHATTERBOX_VERSION, "torch_index": torch_index}),
            encoding="utf-8",
        )
    except BaseException:
        # Remove only the new directory owned by this installation attempt.
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target


def prepare_expressive_voice(
    runtime_directory: Path,
    model_directory: Path,
    reference_audio: Path | None = None,
    *,
    device: str = "auto",
    downloader=None,
    runner=None,
) -> Path:
    """Prepare retained weights and a separate venv; never runs from synthesize()."""
    runtime_directory, model_directory = Path(runtime_directory), Path(model_directory)
    if device not in {"auto", "cpu", "cuda"}:
        raise SpeechError("Le périphérique vocal doit être auto, cpu ou cuda.")
    if chatterbox_voice_is_present(runtime_directory, model_directory):
        return model_directory
    if reference_audio is None and not expressive_model_is_present(model_directory):
        raise SpeechError(
            "Fournissez l’extrait féminin synthétique d’Alicia pour préparer la voix."
        )
    try:
        if downloader is None:
            from huggingface_hub import snapshot_download

            downloader = snapshot_download
        _prepare_model(
            model_directory,
            Path(reference_audio)
            if reference_audio is not None
            else model_directory / "reference.wav",
            downloader,
        )
        _prepare_runtime(runtime_directory, runner or subprocess.run, device)
        return model_directory
    except SpeechError:
        raise
    except Exception:
        raise SpeechError(
            "Préparation de Chatterbox impossible. Vérifiez Internet, l’espace disque et relancez l’installation."
        ) from None
