"""Bounded action data, independent of Qt, Windows and language-model SDKs."""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Literal
from urllib.parse import unquote, urlsplit, urlunsplit

ActionKind = Literal[
    "answer", "clarify", "search_web", "open_url", "open_app", "create_note", "open_folder"
]
KINDS = frozenset(
    {"answer", "clarify", "search_web", "open_url", "open_app", "create_note", "open_folder"}
)
FOLDERS = frozenset({"desktop", "documents", "downloads", "home"})
_LIMITS = {
    "query": 500,
    "url": 2048,
    "app": 100,
    "title": 120,
    "content": 10000,
    "folder": 30,
    "message": 600,
}
_FIELDS = frozenset({"kind", *_LIMITS})
_ALLOWED = {
    "answer": frozenset(),
    "clarify": frozenset({"message"}),
    "search_web": frozenset({"query"}),
    "open_url": frozenset({"url"}),
    "open_app": frozenset({"app"}),
    "create_note": frozenset({"title", "content"}),
    "open_folder": frozenset({"folder"}),
}


class ActionPlanError(ValueError):
    """An invalid plan is never passed to an executor."""


def _has_controls(value: str, *, multiline=False) -> bool:
    return any(
        unicodedata.category(character) in {"Cc", "Cf"}
        and not (multiline and character in "\n\r\t")
        for character in value
    )


def validate_public_url(value: str) -> str:
    """Permit an ordinary public HTTP(S) page, never a local application URI."""
    if not isinstance(value, str) or not value or len(value) > _LIMITS["url"]:
        raise ActionPlanError("L’adresse web est absente ou trop longue.")
    value = value.strip()
    decoded = value
    for _ in range(len(value) + 1):
        previous = decoded
        decoded = unquote(decoded)
        if _has_controls(decoded) or "\\" in decoded:
            raise ActionPlanError("L’adresse web contient des caractères invalides.")
        if decoded == previous:
            break
    if any(character.isspace() for character in value):
        raise ActionPlanError("L’adresse web contient des caractères invalides.")
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
    except (TypeError, ValueError):
        raise ActionPlanError("L’adresse web est invalide.") from None
    if (
        parsed.scheme not in {"https", "http"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 80, 443}
    ):
        raise ActionPlanError("Seules les pages web publiques HTTP ou HTTPS sont acceptées.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            ascii_host = host.encode("idna").decode("ascii").lower().rstrip(".")
        except UnicodeError:
            raise ActionPlanError("Le nom du site web est invalide.") from None
        labels = ascii_host.split(".")
        if (
            len(ascii_host) > 253
            or len(labels) < 2
            or not re.fullmatch(r"[a-z][a-z0-9-]*", labels[-1])
            or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels
            )
            or labels[-1]
            in {"local", "localhost", "internal", "intranet", "test", "invalid", "onion"}
        ):
            raise ActionPlanError("Les adresses de réseau local ne sont pas prises en charge.")
    else:
        if not address.is_global:
            raise ActionPlanError("Les adresses de réseau local ne sont pas prises en charge.")
    return urlunsplit(parsed)


@dataclass(frozen=True, slots=True)
class ActionPlan:
    kind: ActionKind
    query: str = ""
    url: str = ""
    app: str = ""
    title: str = ""
    content: str = ""
    folder: str = ""
    message: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in KINDS:
            raise ActionPlanError("Cette action n’est pas disponible.")
        for name, limit in _LIMITS.items():
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or len(value) > limit
                or _has_controls(value, multiline=name == "content")
            ):
                raise ActionPlanError("Les paramètres de l’action sont invalides.")
            if name != "content":
                object.__setattr__(self, name, value.strip())
            if value and name not in _ALLOWED[self.kind]:
                raise ActionPlanError("Cette action contient des paramètres inattendus.")
        required = {
            "clarify": self.message,
            "search_web": self.query,
            "open_url": self.url,
            "open_app": self.app,
            "create_note": self.content.strip(),
            "open_folder": self.folder,
        }
        if self.kind != "answer" and not required[self.kind]:
            raise ActionPlanError("Un paramètre nécessaire à l’action est absent.")
        if self.kind == "open_folder" and self.folder not in FOLDERS:
            raise ActionPlanError("Ce dossier ne fait pas partie des dossiers disponibles.")
        if self.kind == "open_url":
            object.__setattr__(self, "url", validate_public_url(self.url))

    @classmethod
    def from_dict(cls, value: Mapping) -> ActionPlan:
        return parse_action_plan(value)

    def as_dict(self) -> dict[str, str]:
        return {key: value for key, value in asdict(self).items() if value}


def parse_action_plan(value: Mapping) -> ActionPlan:
    if not isinstance(value, Mapping) or "kind" not in value or set(value) - _FIELDS:
        raise ActionPlanError("Le plan d’action reçu est invalide.")
    return ActionPlan(**value)
