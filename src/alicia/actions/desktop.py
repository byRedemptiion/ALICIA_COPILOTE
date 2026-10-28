"""Small explicit desktop catalogue; no model text is ever a shell command."""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import unicodedata
import uuid
import webbrowser
from pathlib import Path
from typing import Callable

from alicia.actions.models import validate_public_url


class DesktopError(RuntimeError):
    """Safe desktop error suitable for the request panel."""


def _normalise(value: str) -> str:
    return " ".join(
        "".join(
            c
            for c in unicodedata.normalize("NFKD", value.casefold())
            if not unicodedata.combining(c)
        ).split()
    )


_APP_ALIASES = {
    "bloc-notes": "notepad",
    "bloc notes": "notepad",
    "notepad": "notepad",
    "calculatrice": "calculator",
    "calculateur": "calculator",
    "calculator": "calculator",
    "calc": "calculator",
    "paint": "paint",
    "mspaint": "paint",
    "explorateur": "explorer",
    "explorateur de fichiers": "explorer",
    "explorer": "explorer",
    "navigateur": "browser",
    "navigateur web": "browser",
    "browser": "browser",
}
_APP_NAMES = {
    "notepad": "Bloc-notes",
    "calculator": "Calculatrice",
    "paint": "Paint",
    "explorer": "Explorateur",
    "browser": "Navigateur",
}
_APP_EXECUTABLES = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "paint": "mspaint.exe",
    "explorer": "explorer.exe",
}
_KNOWN_FOLDERS = {
    "desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "downloads": "374DE290-123F-4565-9164-39C4925E467B",
}


def app_identifier(name: str) -> str:
    try:
        name = re.sub(r"^(?:(?:le|la|les|un|une|mon|ma|mes)\s+|l['’])", "", _normalise(name))
        return _APP_ALIASES[name]
    except (KeyError, AttributeError, TypeError):
        raise DesktopError(
            "Applications disponibles : Bloc-notes, Calculatrice, Paint, Explorateur et Navigateur."
        ) from None


def _known_folder(name: str) -> Path:
    if name == "home":
        return Path.home()
    if name not in _KNOWN_FOLDERS:
        raise DesktopError("Dossier disponible : Bureau, Documents, Téléchargements ou Accueil.")
    if sys.platform != "win32":
        raise DesktopError("L’ouverture de dossiers est disponible sur votre PC Windows.")
    guid = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(_KNOWN_FOLDERS[name]).bytes_le)
    output = ctypes.c_wchar_p()
    shell = ctypes.windll.shell32
    shell.SHGetKnownFolderPath.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    result = shell.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(output))
    try:
        if result != 0 or not output.value:
            raise DesktopError("Ce dossier Windows n’est pas accessible.")
        return Path(output.value)
    finally:
        if output:
            ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(output, ctypes.c_void_p))


class DesktopActions:
    def __init__(
        self,
        *,
        browser_opener=None,
        process_factory=None,
        folder_resolver=None,
        windows_root=None,
        platform=None,
    ):
        self.browser_opener = browser_opener or webbrowser.open
        self.process_factory = process_factory or subprocess.Popen
        self.folder_resolver = folder_resolver or _known_folder
        self.windows_root = Path(windows_root or os.environ.get("SystemRoot", "C:/Windows"))
        self.platform = platform or sys.platform

    def _launch(self, arguments: list[str], cancelled: Callable[[], bool]) -> None:
        if cancelled():
            return
        try:
            self.process_factory(
                arguments,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, ValueError):
            raise DesktopError("Windows n’a pas pu ouvrir cette application.") from None

    def open_url(self, url: str, *, cancelled=lambda: False) -> bool:
        url = validate_public_url(url)
        if cancelled():
            return False
        try:
            opened = self.browser_opener(url, new=2)
        except Exception:
            raise DesktopError("Le navigateur n’a pas pu être ouvert.") from None
        if not opened:
            raise DesktopError("Aucun navigateur n’a accepté cette ouverture.")
        return True

    def open_report(self, path: Path, report_directory: Path, *, cancelled=lambda: False) -> bool:
        path, report_directory = Path(path), Path(report_directory)
        if (
            path.is_symlink()
            or not path.is_file()
            or path.suffix != ".html"
            or path.parent.resolve() != report_directory.resolve()
        ):
            raise DesktopError("La page de résultats locale n’est pas accessible.")
        if cancelled():
            return False
        try:
            opened = self.browser_opener(path.resolve().as_uri(), new=2)
        except Exception:
            raise DesktopError("Le navigateur n’a pas pu afficher les résultats locaux.") from None
        if not opened:
            raise DesktopError("Aucun navigateur n’a accepté la page de résultats.")
        return True

    def open_app(self, name: str, *, cancelled=lambda: False) -> str:
        identifier = app_identifier(name)
        if identifier == "browser":
            self.open_url("https://duckduckgo.com/", cancelled=cancelled)
            return _APP_NAMES[identifier]
        if self.platform != "win32":
            raise DesktopError("L’ouverture d’applications est disponible sur votre PC Windows.")
        base = self.windows_root if identifier == "explorer" else self.windows_root / "System32"
        executable = base / _APP_EXECUTABLES[identifier]
        if not executable.is_file():
            raise DesktopError(
                "Cette application Windows n’est pas installée à l’emplacement attendu."
            )
        self._launch([str(executable)], cancelled)
        return _APP_NAMES[identifier]

    def open_folder(self, name: str, *, cancelled=lambda: False) -> Path:
        if name not in {*_KNOWN_FOLDERS, "home"}:
            raise DesktopError(
                "Dossier disponible : Bureau, Documents, Téléchargements ou Accueil."
            )
        if self.platform != "win32":
            raise DesktopError("L’ouverture de dossiers est disponible sur votre PC Windows.")
        path = Path(self.folder_resolver(name))
        if not path.is_dir():
            raise DesktopError("Ce dossier Windows n’est pas accessible.")
        executable = self.windows_root / "explorer.exe"
        if not executable.is_file():
            raise DesktopError("L’Explorateur Windows est introuvable.")
        self._launch([str(executable), str(path)], cancelled)
        return path
