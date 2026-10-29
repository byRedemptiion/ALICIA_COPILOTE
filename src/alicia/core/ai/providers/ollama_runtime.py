"""Démarrer Ollama tout seul quand c'est l'IA choisie, et télécharger son modèle au besoin.

ALICIA ne lance que le programme Ollama officiel déjà installé (jamais une commande libre),
et seulement pour une adresse locale (127.0.0.1 / localhost). Si c'est elle qui l'a
démarré, elle l'arrête en se fermant pour libérer la mémoire de la carte graphique.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import httpx

from alicia.core.errors import AliciaError

log = logging.getLogger("alicia.ai")

DOWNLOAD_URL = "https://ollama.com/download"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def is_local(base_url: str) -> bool:
    return (urlparse(base_url).hostname or "") in ("127.0.0.1", "localhost", "::1")


def find_ollama() -> Path | None:
    """ollama.exe : dans le PATH, sinon à l'emplacement d'installation par défaut."""
    found = shutil.which("ollama")
    if found:
        return Path(found)
    candidates = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        candidates += [
            Path(local) / "Programs" / "Ollama" / "ollama.exe",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Ollama" / "ollama.exe",
        ]
    for path in candidates:
        if path.is_file():
            return path
    return None


class OllamaRuntime:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        transport: httpx.BaseTransport | None = None,
        launcher: Callable[[Path], subprocess.Popen] | None = None,
        finder: Callable[[], Path | None] = find_ollama,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._transport = transport
        self._launcher = launcher or self._launch
        self._finder = finder
        self.process: subprocess.Popen | None = None  # seulement si ALICIA l'a démarré

    def _client(self, timeout: float = 3.0) -> httpx.Client:
        return httpx.Client(timeout=timeout, transport=self._transport)

    def running(self) -> bool:
        try:
            with self._client(2.0) as client:
                return client.get(f"{self.base_url}/api/version").status_code == 200
        except httpx.HTTPError:
            return False

    @staticmethod
    def _launch(exe: Path) -> subprocess.Popen:
        return subprocess.Popen(  # programme fixe (ollama.exe), aucune commande libre
            [str(exe), "serve"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
        )

    def ensure_running(self, wait_s: float = 20.0) -> bool:
        """True si Ollama répond (déjà lancé, ou démarré par ALICIA)."""
        if self.running():
            return False
        if not is_local(self.base_url):
            raise AliciaError(
                f"Ollama ne répond pas à {self.base_url}. Démarre-le sur cette machine.",
                detail="adresse distante : pas de démarrage automatique",
            )
        exe = self._finder()
        if exe is None:
            raise AliciaError(
                f"Ollama n'est pas installé sur ce PC. Télécharge-le sur {DOWNLOAD_URL}, "
                "ou choisis Gemini (bouton IA).",
                detail="ollama.exe introuvable",
            )
        log.info("Démarrage d'Ollama : %s", exe)
        try:
            self.process = self._launcher(exe)
        except OSError as exc:
            raise AliciaError("Impossible de démarrer Ollama.", detail=repr(exc)) from exc
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            if self.running():
                log.info("Ollama prêt")
                return True
            time.sleep(0.5)
        raise AliciaError(
            "Ollama a été lancé mais ne répond pas encore. Réessaie dans un instant.",
            detail=f"pas de réponse en {wait_s:.0f} s",
        )

    def has_model(self) -> bool:
        with self._client(5.0) as client:
            response = client.get(f"{self.base_url}/api/tags")
        names = {m.get("name", "") for m in response.json().get("models", [])}
        wanted = self.model if ":" in self.model else f"{self.model}:latest"
        return wanted in names or self.model in names

    def pull(self, progress: Callable[[int], None] | None = None) -> None:
        """Télécharge le modèle (plusieurs Go) ; progress reçoit un pourcentage."""
        last = -1
        with self._client(None) as client:  # type: ignore[arg-type]
            with client.stream(
                "POST", f"{self.base_url}/api/pull", json={"model": self.model}
            ) as response:
                if response.status_code >= 400:
                    raise AliciaError(
                        f"Ollama refuse de télécharger « {self.model} ».",
                        detail=f"HTTP {response.status_code}",
                    )
                for line in response.iter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if "error" in data:
                        raise AliciaError(
                            f"Téléchargement du modèle « {self.model} » impossible.",
                            detail=str(data["error"]),
                        )
                    total, done = data.get("total"), data.get("completed")
                    if total and done is not None and progress is not None:
                        percent = int(done * 100 / total)
                        if percent != last:
                            last = percent
                            progress(percent)
        log.info("Modèle Ollama « %s » téléchargé", self.model)

    def stop(self) -> None:
        """Arrête Ollama seulement si c'est ALICIA qui l'a démarré."""
        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            process.terminate()
            log.info("Ollama arrêté (démarré par ALICIA)")
