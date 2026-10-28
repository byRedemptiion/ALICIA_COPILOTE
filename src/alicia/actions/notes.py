"""Private, bounded text notes and generated reports, without overwriting files."""

from __future__ import annotations

import os
import re
import secrets
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path


class NoteError(RuntimeError):
    """Safe note error; paths and document text are not logged."""


def default_notes_directory() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return root / "Alicia" / "notes"
    return (
        Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
        / "alicia"
        / "notes"
    )


class NoteStore:
    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory) if directory is not None else default_notes_directory()

    def _directory(self) -> Path:
        # Refuse links anywhere in the selected path rather than following an
        # unexpected redirect outside the dedicated Alicia directory.
        directory = self.directory.absolute()
        if any(
            path.is_symlink() or getattr(path, "is_junction", lambda: False)()
            for path in (directory, *directory.parents)
        ):
            raise NoteError("Le dossier de notes contient un lien symbolique ; il est conservé.")
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise NoteError("Le dossier de notes n’est pas accessible.") from None
        if (
            not directory.is_dir()
            or directory.is_symlink()
            or getattr(directory, "is_junction", lambda: False)()
        ):
            raise NoteError("Le dossier de notes n’est pas accessible.")
        return directory

    def _write(
        self, title: str, content: str, suffix: str, *, cancelled=lambda: False
    ) -> Path | None:
        if cancelled():
            return None
        directory = self._directory()
        slug = re.sub(r"[^\w -]", "", title, flags=re.UNICODE).strip(" ._-")[:70] or "Note Alicia"
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        path = directory / f"{slug}-{stamp}-{secrets.token_hex(4)}{suffix}"
        if cancelled():
            return None
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=".alicia-note-",
                suffix=".tmp",
                dir=directory,
                delete=False,
            ) as destination:
                temporary = Path(destination.name)
                if cancelled():
                    return None
                destination.write(content)
                destination.flush()
                os.fsync(destination.fileno())
            if cancelled():
                return None
            # A hard link publishes the completed file atomically and refuses
            # any existing destination on both NTFS and POSIX. No replace call
            # can overwrite a user file, even under a forced name collision.
            os.link(temporary, path, follow_symlinks=False)
            return path
        except OSError:
            raise NoteError("La note n’a pas pu être enregistrée.") from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def create_note(self, title: str, content: str, *, cancelled=lambda: False) -> Path | None:
        if (
            not isinstance(content, str)
            or not content.strip()
            or len(content) > 10000
            or "\x00" in content
        ):
            raise NoteError("La note doit contenir entre 1 et 10 000 caractères de texte.")
        title = title.strip() if isinstance(title, str) else ""
        title = title or "Note Alicia"
        if (
            len(title) > 120
            or any(ord(c) < 32 for c in title)
            or any(c in title for c in "/\\")
            or title in {".", ".."}
        ):
            raise NoteError("Choisissez un titre de note simple, sans chemin de fichier.")
        extension = Path(title).suffix.lower()
        if extension and extension not in {".txt", ".md"}:
            raise NoteError("Je peux préparer une note .txt ou .md avec cette action.")
        suffix = extension or ".txt"
        if extension:
            title = title[: -len(extension)]
        return self._write(title, content, suffix, cancelled=cancelled)

    def create_report(self, content: str, *, cancelled=lambda: False) -> Path | None:
        if not isinstance(content, str) or not content or len(content) > 100000:
            raise NoteError("La page de résultats dépasse la taille autorisée.")
        return self._write("Recherche Alicia", content, ".html", cancelled=cancelled)
