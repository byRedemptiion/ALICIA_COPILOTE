"""Écrire un réglage dans le fichier du joueur (%APPDATA%\\Alicia\\alicia.toml).

Modification ciblée d'une ligne : les commentaires et les autres réglages du fichier
sont conservés. Le résultat est relu avant d'être enregistré : jamais de fichier cassé.
"""

from __future__ import annotations

import json
import logging
import re
import tomllib
from pathlib import Path

from alicia.core.config import data_dir

log = logging.getLogger("alicia.config")


def user_config_file() -> Path:
    return data_dir() / "alicia.toml"


def _value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def set_value(section: str, key: str, value: object, path: Path | None = None) -> Path:
    """Écrit `key = value` dans `[section]` (créés au besoin)."""
    path = path or user_config_file()
    text = path.read_text("utf-8") if path.is_file() else ""
    lines = text.splitlines()
    line = f"{key} = {_value(value)}"
    header = re.compile(r"^\s*\[([^\]]+)\]\s*(#.*)?$")
    start = next(
        (
            i
            for i, raw in enumerate(lines)
            if (m := header.match(raw)) and m.group(1).strip() == section
        ),
        None,
    )
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"[{section}]", line]
    else:
        end = next((i for i in range(start + 1, len(lines)) if header.match(lines[i])), len(lines))
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
        for i in range(start + 1, end):
            if pattern.match(lines[i]):
                lines[i] = line
                break
        else:
            insert = end
            while insert > start + 1 and not lines[insert - 1].strip():
                insert -= 1
            lines.insert(insert, line)
    result = "\n".join(lines) + "\n"
    tomllib.loads(result)  # vérification avant écriture
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(result, encoding="utf-8")
    tmp.replace(path)
    log.info("Réglage enregistré : [%s] %s = %s", section, key, _value(value))
    return path


def user_env_file() -> Path:
    return data_dir() / ".env"


def set_env(key: str, value: str, path: Path | None = None) -> Path:
    """Écrit `KEY=valeur` dans le .env du joueur (clés d'API). La valeur n'est jamais journalisée."""
    path = path or user_env_file()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
        raise ValueError(f"Nom de variable invalide : {key}")
    if any(c in value for c in "\r\n"):
        raise ValueError("La valeur ne doit pas contenir de retour à la ligne.")
    lines = path.read_text("utf-8").splitlines() if path.is_file() else []
    lines = [line for line in lines if not re.match(rf"^\s*{key}\s*=", line)]
    lines.append(f"{key}={value.strip()}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)
    log.info("%s enregistré dans %s (valeur masquée)", key, path)
    return path
