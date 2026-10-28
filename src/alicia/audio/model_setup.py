"""Téléchargement explicite du modèle vocal depuis le site HTTPS de son éditeur."""

import hashlib
import json
import os
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

import httpx

from alicia.audio.ports import SpeechError

MODEL_NAME = "vosk-model-small-fr-0.22"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
MAX_DOWNLOAD = 128 * 1024 * 1024
MAX_EXTRACTED = 512 * 1024 * 1024


def model_is_present(path: Path) -> bool:
    return all(
        (path / name).is_file() and (path / name).stat().st_size > 0
        for name in ("am/final.mdl", "conf/model.conf", "conf/mfcc.conf")
    ) and any(
        graph.is_file() and graph.stat().st_size > 0 for graph in (path / "graph").glob("*.fst")
    )


def prepare_voice_model(target: Path, client: httpx.Client | None = None) -> Path:
    if target.is_symlink():
        raise SpeechError("Le dossier du modèle est un lien symbolique ; son contenu est préservé.")
    if model_is_present(target):
        return target
    if target.exists():
        raise SpeechError(
            "Le dossier du modèle existe mais est incomplet. Déplacez-le avant de relancer l’installation."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    owned_client = client is None
    connection = client or httpx.Client(follow_redirects=False, timeout=60)
    try:
        with tempfile.TemporaryDirectory(prefix="alicia-model-", dir=target.parent) as temp:
            archive = Path(temp) / "model.zip"
            digest = hashlib.sha256()
            count = 0
            with connection.stream("GET", MODEL_URL, follow_redirects=False) as response:
                if response.status_code != 200:
                    raise SpeechError(
                        "Le site officiel du modèle vocal est inaccessible. Vérifiez Internet puis relancez Installer_Alicia.bat."
                    )
                with archive.open("wb") as output:
                    for chunk in response.iter_bytes():
                        count += len(chunk)
                        if count > MAX_DOWNLOAD:
                            raise SpeechError(
                                "Le téléchargement du modèle dépasse la taille autorisée."
                            )
                        digest.update(chunk)
                        output.write(chunk)
            extraction = Path(temp) / "extracted"
            with ZipFile(archive) as bundle:
                entries = bundle.infolist()
                if sum(entry.file_size for entry in entries) > MAX_EXTRACTED or len(entries) > 5000:
                    raise SpeechError("L’archive du modèle dépasse les limites autorisées.")
                for entry in entries:
                    name = PurePosixPath(entry.filename)
                    mode = entry.external_attr >> 16
                    if (
                        name.is_absolute()
                        or not name.parts
                        or name.parts[0] != MODEL_NAME
                        or ".." in name.parts
                        or "\\" in entry.filename
                        or ":" in entry.filename
                        or stat.S_ISLNK(mode)
                    ):
                        raise SpeechError("L’archive du modèle contient un chemin invalide.")
                # ZipFile verifies CRCs while extracting; TLS verification stays enabled.
                bundle.extractall(extraction)
            model = extraction / MODEL_NAME
            if not model_is_present(model):
                raise SpeechError(
                    "L’archive ne contient pas les fichiers attendus du modèle français."
                )
            (model / ".alicia-model.json").write_text(
                json.dumps(
                    {
                        "source": MODEL_URL,
                        "archive_sha256": digest.hexdigest(),
                        "downloaded_at": datetime.now(UTC).isoformat(),
                        "integrity": "HTTPS éditeur et CRC ZIP ; SHA256 calculé, pas de signature indépendante",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            os.rename(model, target)
            return target
    except SpeechError:
        raise
    except (httpx.HTTPError, OSError, BadZipFile, RuntimeError):
        raise SpeechError(
            "Préparation du modèle vocal impossible. Vérifiez la connexion, le disque et relancez l’installation."
        ) from None
    finally:
        if owned_client:
            connection.close()
