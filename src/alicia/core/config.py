"""Configuration centralisée.

Ordre de priorité (le premier gagne) :
1. variables d'environnement (``ALICE_AI_PROVIDER``, ``ALICE_LOG_LEVEL``, clés API) ;
2. fichier ``.env`` (dossier courant, puis dossier de données d'Alicia) ;
3. ``alicia.toml`` (dossier courant, puis dossier de données d'Alicia) ;
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

from alicia.core.errors import ConfigError

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
    return Path(base) / "Alicia"


def migrate_legacy_dirs() -> list[str]:
    """Renomme les dossiers de l'ancien nom « Alice » en « Alicia » (modèles, logs, config)."""
    moved = []
    for new in (data_dir(), state_dir()):
        old = new.with_name("Alice")
        if old.is_dir() and not new.exists():
            try:
                old.rename(new)
                moved.append(f"{old} → {new}")
            except OSError:
                pass  # dossier occupé : on repartira de zéro, sans bloquer le démarrage
    return moved


def state_dir() -> Path:
    """Dossier des fichiers produits (logs)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "Alicia"


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
    web_search: bool = False


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
class VoiceSettings:
    speak_answers: bool = True  # lire les réponses à voix haute
    stt: str = "local"  # local (faster-whisper) | gemini (audio envoyé au modèle)
    whisper_model: str = "large-v3-turbo"
    tts_engine: str = "edge"  # edge | kokoro
    kokoro_voice: str = "ff_siwis"
    kokoro_speed: float = 1.05
    tts_voice: str = "fr-FR-DeniseNeural"
    tts_rate: str = "+8%"
    output_device: str = ""  # vide = sortie Windows par défaut ; sinon une partie du nom
    input_device: str = ""  # vide = micro Windows par défaut ; sinon une partie du nom
    max_record_s: float = 30.0
    sample_rate: int = 16000


@dataclass(frozen=True)
class AppEntry:
    launch: str  # chemin d'un .exe ou lien (discord://, spotify:)
    process: str = ""  # nom du processus pour « ferme X » (ex. Discord.exe)


DEFAULT_APPS = {
    "discord": AppEntry("discord://", "Discord.exe"),
    "spotify": AppEntry("spotify:", "Spotify.exe"),
    "steam": AppEntry("steam://open/main", "steam.exe"),
    "battle.net": AppEntry("battlenet://", "Battle.net.exe"),
}


@dataclass(frozen=True)
class ActionSettings:
    enabled: bool = True
    shutdown_delay_s: int = 60
    confirm_timeout_s: float = 20.0
    apps: dict[str, AppEntry] = field(default_factory=lambda: dict(DEFAULT_APPS))


@dataclass(frozen=True)
class UpdateSettings:
    repo: str = "byRedemptiion/ALICIA_COPILOTE"
    branch: str = "alice-v0.3"
    check_on_start: bool = True
    token: Secret = field(default_factory=lambda: Secret(None))


@dataclass(frozen=True)
class Settings:
    ai: AISettings
    capture: CaptureSettings
    log_level: str
    game_profile: str
    hotkey_analyze: str = ""
    hotkey_talk: str = ""
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    actions: ActionSettings = field(default_factory=ActionSettings)
    update: UpdateSettings = field(default_factory=UpdateSettings)
    ui_mode: str = "orb"  # "orb" : seule la bulle d'ALICIA à l'écran ; "full" : le panneau
    orb_size: int = 210
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


def _actions(section: dict[str, Any]) -> ActionSettings:
    apps: dict[str, AppEntry] = {}
    raw_apps = section.get("apps", {})
    if not isinstance(raw_apps, dict):
        raise ConfigError("La section [actions.apps] est invalide.")
    for name, value in raw_apps.items():
        if isinstance(value, str):
            entry = AppEntry(value.strip())
        elif isinstance(value, dict) and value.get("launch"):
            entry = AppEntry(str(value["launch"]).strip(), str(value.get("process", "")).strip())
        else:
            raise ConfigError(f"Application « {name} » invalide dans [actions.apps].")
        apps[str(name).strip().lower()] = entry
    return ActionSettings(
        enabled=bool(section.get("enabled", True)),
        shutdown_delay_s=_number(section, "shutdown_delay_s", int, 10)
        if "shutdown_delay_s" in section
        else 60,
        confirm_timeout_s=float(section.get("confirm_timeout_s", 20)),
        apps=apps or dict(DEFAULT_APPS),
    )


def _choice(section: dict[str, Any], key: str, default: str, allowed: tuple[str, ...]) -> str:
    value = str(section.get(key, default)).strip().lower()
    if value not in allowed:
        raise ConfigError(
            f"Réglage « {key} » invalide : « {value} » (choix : {', '.join(allowed)})."
        )
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
    data = tomllib.loads(resources.files("alicia").joinpath("default.toml").read_text("utf-8"))
    for candidate in (
        user_dir / "alice.toml",  # ancien nom, encore lu
        user_dir / "alicia.toml",
        cwd / "alice.toml",
        cwd / "alicia.toml",
    ):
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
    voice = _section(data, "voice")

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
            web_search=bool(ai.get("web_search", False)),
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
        hotkey_talk=str(_section(data, "hotkeys").get("talk", "")).strip(),
        actions=_actions(_section(data, "actions")),
        ui_mode=_choice(_section(data, "ui"), "mode", "orb", ("orb", "full")),
        update=UpdateSettings(
            repo=str(_section(data, "update").get("repo", UpdateSettings.repo)).strip(),
            branch=str(_section(data, "update").get("branch", UpdateSettings.branch)).strip(),
            check_on_start=bool(_section(data, "update").get("check_on_start", True)),
            token=Secret(env.get("ALICIA_GITHUB_TOKEN") or env.get("GITHUB_TOKEN")),
        ),
        orb_size=min(
            _number({"orb_size": _section(data, "ui").get("orb_size", 210)}, "orb_size", int, 120),
            600,
        ),
        voice=VoiceSettings(
            speak_answers=bool(voice.get("speak_answers", True)),
            stt=_choice(voice, "stt", "local", ("local", "gemini")),
            whisper_model=str(voice.get("whisper_model", "large-v3-turbo")).strip(),
            tts_engine=_choice(voice, "tts_engine", "edge", ("edge", "kokoro")),
            kokoro_voice=str(voice.get("kokoro_voice", "ff_siwis")).strip(),
            kokoro_speed=_number({"v": voice.get("kokoro_speed", 1.05)}, "v", float, 0.5),
            tts_voice=str(voice.get("tts_voice", "fr-FR-DeniseNeural")).strip(),
            tts_rate=str(voice.get("tts_rate", "+0%")).strip(),
            output_device=str(voice.get("output_device", "")).strip(),
            input_device=str(voice.get("input_device", "")).strip(),
            max_record_s=_number(voice, "max_record_s", float, 2),
            sample_rate=_number(voice, "sample_rate", int, 8000),
        ),
        sources=tuple(sources),
        captures_dir=cwd / "captures",
    )
