"""Installation explicite des poids Kokoro officiels, sans téléchargement à l’usage."""

import hashlib
import json
import os
import re
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from zipfile import BadZipFile, ZipFile

import httpx

from alicia.audio.ports import SpeechError

RELEASE = "model-files-v1.1"
_BASE_URL = f"https://github.com/thewh1teagle/kokoro-onnx/releases/download/{RELEASE}"
ASSETS = {
    "kokoro-v1.0.onnx": f"{_BASE_URL}/kokoro-v1.0.onnx",
    "voices-v1.0.bin": f"{_BASE_URL}/voices-v1.0.bin",
}
# Lengths verified against the versioned GitHub release, not a cryptographic signature.
ASSET_BYTES = {"kokoro-v1.0.onnx": 325505369, "voices-v1.0.bin": 28214398}
MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
MODEL_MIN_BYTES = 50 * 1024 * 1024
_MANIFEST = ".alicia-neural.json"
_DOWNLOAD_HOSTS = {
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
}


def _digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def neural_voice_is_present(path: Path) -> bool:
    """Recheck retained files against the locally recorded download fingerprints."""
    if path.is_symlink() or not path.is_dir():
        return False
    try:
        manifest_path = path / _MANIFEST
        if manifest_path.is_symlink():
            return False
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        records = manifest["files"]
        if manifest["release"] != RELEASE or not isinstance(records, dict):
            return False
        total = 0
        for name, url in ASSETS.items():
            asset = path / name
            record = records[name]
            if asset.is_symlink() or not asset.is_file():
                return False
            size = asset.stat().st_size
            total += size
            if (
                size != ASSET_BYTES[name]
                or size != record["size"]
                or record["source"] != url
                or not re.fullmatch(r"[a-f0-9]{64}", record["sha256"])
                or _digest(asset) != record["sha256"]
            ):
                return False
        return (
            total <= MAX_DOWNLOAD_BYTES
            and (path / "kokoro-v1.0.onnx").stat().st_size >= MODEL_MIN_BYTES
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _allowed_download(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname in _DOWNLOAD_HOSTS
            and parsed.username is None
            and parsed.password is None
            and parsed.port in {None, 443}
            and not parsed.fragment
        )
    except ValueError:
        return False


def _download(client, url: str, destination: Path, remaining_bytes: int, deadline: float) -> int:
    for attempt in range(4):
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            raise SpeechError("Le délai d’installation de la voix naturelle est dépassé.")
        with client.stream(
            "GET", url, follow_redirects=False, timeout=min(60, remaining_seconds)
        ) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                target = urljoin(url, response.headers.get("location", ""))
                if (
                    attempt >= 3
                    or not response.headers.get("location")
                    or not _allowed_download(target)
                ):
                    raise SpeechError(
                        "Le téléchargement vocal demande une redirection non autorisée."
                    )
                url = target
                continue
            if response.status_code != 200:
                raise SpeechError(
                    "La voix naturelle officielle est inaccessible. Vérifiez Internet puis relancez l’installation."
                )
            count = 0
            with destination.open("wb") as output:
                for chunk in response.iter_bytes():
                    count += len(chunk)
                    if count > remaining_bytes:
                        raise SpeechError(
                            "La voix naturelle dépasse la taille de téléchargement autorisée."
                        )
                    if time.monotonic() >= deadline:
                        raise SpeechError(
                            "Le délai d’installation de la voix naturelle est dépassé."
                        )
                    output.write(chunk)
            return count
    raise SpeechError("Le téléchargement vocal n’a pas abouti.")


def _validate_assets(directory: Path) -> None:
    if (directory / "kokoro-v1.0.onnx").stat().st_size < MODEL_MIN_BYTES:
        raise SpeechError("Le modèle vocal téléchargé est incomplet ou invalide.")
    with ZipFile(directory / "voices-v1.0.bin") as voices:
        entries = voices.infolist()
        if (
            len(entries) > 1000
            or sum(entry.file_size for entry in entries) > 200 * 1024 * 1024
            or "ff_siwis.npy" not in voices.namelist()
        ):
            raise SpeechError("L’archive de voix ne contient pas la voix française attendue.")
        if voices.testzip() is not None:
            raise SpeechError("L’archive de voix est corrompue.")
        with voices.open("ff_siwis.npy") as voice:
            if voice.read(6) != b"\x93NUMPY":
                raise SpeechError("La voix française téléchargée est invalide.")


def prepare_neural_voice(target: Path, client: httpx.Client | None = None) -> Path:
    """Download once over verified HTTPS; preserve every pre-existing incomplete target."""
    if target.is_symlink():
        raise SpeechError("Le dossier vocal est un lien symbolique ; il est conservé.")
    if neural_voice_is_present(target):
        return target
    if target.exists():
        raise SpeechError(
            "Le dossier de voix naturelle existe mais est incomplet ou modifié. Déplacez-le avant de relancer l’installation."
        )
    connection = client
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        connection = client or httpx.Client(follow_redirects=False, timeout=60)
        with tempfile.TemporaryDirectory(prefix="alicia-kokoro-", dir=target.parent) as temporary:
            prepared = Path(temporary) / "voice"
            prepared.mkdir()
            remaining = MAX_DOWNLOAD_BYTES
            deadline = time.monotonic() + 600
            records = {}
            for name, source in ASSETS.items():
                output = prepared / name
                size = _download(connection, source, output, remaining, deadline)
                if size != ASSET_BYTES[name]:
                    raise SpeechError(
                        "Les poids vocaux sont incomplets ou d’une version inattendue."
                    )
                remaining -= size
                records[name] = {"source": source, "size": size, "sha256": _digest(output)}
            _validate_assets(prepared)
            (prepared / _MANIFEST).write_text(
                json.dumps(
                    {
                        "release": RELEASE,
                        "files": records,
                        "downloaded_at": datetime.now(UTC).isoformat(),
                        "integrity": "HTTPS officiel et CRC NPZ ; SHA256 calculé, sans signature indépendante",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            if target.exists() or target.is_symlink():
                raise SpeechError(
                    "Le dossier vocal a été créé pendant l’installation ; son contenu est conservé."
                )
            os.rename(prepared, target)
            return target
    except SpeechError:
        raise
    except (httpx.HTTPError, OSError, BadZipFile, ValueError, RuntimeError, NotImplementedError):
        raise SpeechError(
            "Installation de la voix naturelle impossible. Vérifiez Internet et le disque puis relancez l’installation."
        ) from None
    finally:
        if client is None and connection is not None:
            connection.close()
