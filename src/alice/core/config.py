"""Configuration centralisée.

Ordre de priorité (le premier gagne) :
1. variables d'environnement (``ALICE_AI_PROVIDER``, ``ALICE_LOG_LEVEL``, clés API) ;
2. fichier ``.env`` (dossier courant, puis dossier de données d'Alice) ;
3. ``alice.toml`` (dossier courant, puis dossier de données d'Alice) ;
4. ``default.toml`` livré avec le paquet.

Les clés API ne vivent que dans l'environnement ou le ``.env`` : jamais dans un TOML ni dans Git.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from alice.core.errors import ConfigError

PROVIDERS = ("gemini", "ollama", "fake")
CAPTURE_BACKENDS = ("auto", "wgc", "printwindow")


class Secret:
    """Valeur secrète qui ne s'affiche jamais en clair (repr, logs, exceptions)."""

    __slots__ = ("_value",)

    def __init__(self, value: str | None) -> None:
        self._value = (value or "").strip()

    def get(self) -> str:
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __repr__(self) -> str:
        return "Secret(***)" if self._value else "Secret(<vide>)"

    __str__ = __repr__


def data_dir() -> Path:
    """Dossier des données utilisateur (config locale, .env de la version packagée)."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "Alice"


def state_dir() -> Path:
    """Dossier des fichiers produits (logs)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "Alice"


@dataclass(frozen=True)
class GeminiSettings:
    model: str
    base_url: str
    api_key: Secret
    thinking_budget: int | None = None
    thinking_level: str | None = None
    fallback_models: tuple[str, ...] = ()


@dataclass(frozen=True)
class OllamaSettings:
    model: str
    base_url: str
    keep_alive: str


@dataclass(frozen=True)
class AISettings:
    provider: str
    timeout_s: float
    max_output_tokens: int
    temperature: float
    history_turns: int
    gemini: GeminiSettings
    ollama: OllamaSettings


@dataclass(frozen=True)
class CaptureSettings:
    backend: str
    monitor_fallback: bool
    max_image_side: int
    jpeg_quality: int
    keep_last_frames: int
    save_captures: bool
    timeout_s: float


@dataclass(frozen=True)
class Settings:
    ai: AISettings
    capture: CaptureSettings
    log_level: str
    game_profile: str
    hotkey_analyze: str = ""
    sources: tuple[str, ...] = field(default_factory=tuple)
    log_dir: Path = field(default_factory=lambda: state_dir() / "logs")
    captures_dir: Path = field(default_factory=lambda: Path.cwd() / "captures")


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Le fichier de configuration {path} est invalide : {exc}") from exc


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"La section [{name}] de la configuration est invalide.")
    return value


def _number(section: dict[str, Any], key: str, kind: type, minimum: float) -> Any:
    try:
        value = kind(section[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"Réglage « {key} » manquant ou invalide.") from exc
    if value < minimum:
        raise ConfigError(f"Réglage « {key} » trop petit (minimum {minimum}).")
    return value


def load_settings(
    *,
    cwd: Path | None = None,
    environ: dict[str, str] | None = None,
    user_dir: Path | None = None,
) -> Settings:
    cwd = cwd or Path.cwd()
    user_dir = user_dir or data_dir()
    env_os = dict(os.environ if environ is None else environ)

    sources: list[str] = ["default.toml"]
    data = tomllib.loads(resources.files("alice").joinpath("default.toml").read_text("utf-8"))
    for candidate in (user_dir / "alice.toml", cwd / "alice.toml"):
        if candidate.is_file():
            data = _merge(data, _read_toml(candidate))
            sources.append(str(candidate))

    env: dict[str, str] = {}
    for candidate in (user_dir / ".env", cwd / ".env"):
        if candidate.is_file():
            env.update({k: v for k, v in dotenv_values(candidate).items() if v is not None})
            sources.append(str(candidate))
    env.update(env_os)

    ai = _section(data, "ai")
    gemini = _section(ai, "gemini")
    ollama = _section(ai, "ollama")
    capture = _section(data, "capture")

    provider = str(env.get("ALICE_AI_PROVIDER") or ai.get("provider", "gemini")).strip().lower()
    if provider not in PROVIDERS:
        raise ConfigError(
            f"Fournisseur IA inconnu « {provider} » (choix : {', '.join(PROVIDERS)})."
        )
    backend = str(capture.get("backend", "auto")).strip().lower()
    if backend not in CAPTURE_BACKENDS:
        raise ConfigError(f"Backend de capture inconnu « {backend} ».")
    level = str(env.get("ALICE_LOG_LEVEL") or _section(data, "logging").get("level", "INFO"))
    level = level.strip().upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        raise ConfigError(f"Niveau de log inconnu « {level} ».")

    thinking_budget = gemini.get("thinking_budget")
    return Settings(
        ai=AISettings(
            provider=provider,
            timeout_s=_number(ai, "timeout_s", float, 1),
            max_output_tokens=_number(ai, "max_output_tokens", int, 16),
            temperature=_number(ai, "temperature", float, 0),
            history_turns=_number(ai, "history_turns", int, 0),
            gemini=GeminiSettings(
                model=str(gemini.get("model", "")).strip(),
                base_url=str(gemini.get("base_url", "")).rstrip("/"),
                api_key=Secret(env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY")),
                thinking_budget=int(thinking_budget) if thinking_budget is not None else None,
                thinking_level=(
                    str(gemini["thinking_level"]) if "thinking_level" in gemini else None
                ),
                fallback_models=tuple(
                    str(m).strip() for m in gemini.get("fallback_models", []) if str(m).strip()
                ),
            ),
            ollama=OllamaSettings(
                model=str(ollama.get("model", "")).strip(),
                base_url=str(ollama.get("base_url", "")).rstrip("/"),
                keep_alive=str(ollama.get("keep_alive", "10m")),
            ),
        ),
        capture=CaptureSettings(
            backend=backend,
            monitor_fallback=bool(capture.get("monitor_fallback", True)),
            max_image_side=_number(capture, "max_image_side", int, 256),
            jpeg_quality=min(_number(capture, "jpeg_quality", int, 30), 100),
            keep_last_frames=_number(capture, "keep_last_frames", int, 1),
            save_captures=bool(capture.get("save_captures", False)),
            timeout_s=_number(capture, "timeout_s", float, 0.2),
        ),
        log_level=level,
        game_profile=str(_section(data, "game").get("profile", "auto")).strip().lower(),
        hotkey_analyze=str(_section(data, "hotkeys").get("analyze", "")).strip(),
        sources=tuple(sources),
        captures_dir=cwd / "captures",
    )
