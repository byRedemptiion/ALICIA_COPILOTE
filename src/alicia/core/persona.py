"""Personnages : le même programme, deux visages (ALICIA ou VERIS).

Chacun choisit le sien dans Réglages → Général (``[ui] persona`` dans alicia.toml) :
nom, mot de réveil, portrait, couleurs et voix changent ; le code et les mises à jour
restent communs. Le personnage est fixé au démarrage (changer = redémarrer).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Persona:
    key: str
    name: str  # « Alicia »
    title: str  # « ALICIA »
    wake_name: str  # forme normalisée, sans accent
    wake_forms: frozenset[str]
    portrait: str  # fichier dans alicia.assets
    icon: str
    # Zone du visage dans le portrait, pour le rond (x, y, largeur, hauteur en fractions).
    face_crop: tuple[float, float, float, float]
    identity: str  # première phrase du prompt système
    voice_engine: str  # moteur de voix proposé par défaut
    colors: dict[str, str] = field(default_factory=dict)
    states: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    round_portrait: bool = False  # portrait déjà rond : même cadrage dans le panneau


ALICIA = Persona(
    key="alicia",
    name="Alicia",
    title="ALICIA",
    wake_name="alicia",
    wake_forms=frozenset(
        {
            "alicia",
            "alissia",
            "alicya",
            "alisia",
            "alysia",
            "alycia",
            "allicia",
            "aliciaa",
            "elicia",
            "alice",
            "alisa",
        }
    ),
    portrait="alicia.png",
    icon="alicia.ico",
    face_crop=(0.2, 0.07, 0.58, 0.58),
    identity="Tu es Alicia, une copilote assise virtuellement à côté du joueur.",
    voice_engine="edge",
)

VERIS = Persona(
    key="veris",
    name="Veris",
    title="VERIS",
    wake_name="veris",
    wake_forms=frozenset(
        {
            "veris",
            "verise",
            "verisse",
            "verice",
            "veriss",
            "verris",
            "vairis",
            "verys",
            "beris",
            "ferris",
            "feris",
            "veres",
        }
    ),
    portrait="veris.png",
    icon="veris.ico",
    face_crop=(0.06, 0.09, 0.9, 0.9),  # le cercle néon du médaillon
    identity=(
        "Tu es VERIS, un petit robot copilote assis virtuellement à côté du joueur "
        "(tu parles de toi au masculin)."
    ),
    voice_engine="veris",
    round_portrait=True,
    colors={
        "BG": "#07041c",
        "PANEL": "rgba(22, 12, 58, 0.74)",
        "BORDER": "#3a2a86",
        "CYAN": "#2da8ff",
        "CYAN_SOFT": "#8fd0ff",
        "PINK": "#7c4dff",
        "PINK_SOFT": "#b39dff",
        "RED": "#4a2bb8",
        "GOLD": "#5b9bff",
        "TEXT": "#eeeaff",
        "MUTED": "#8f86c4",
        "DEEP": "#0e0830",
        "GLOW": "#1c1060",
    },
    states={
        "idle": (124, 77, 255),
        "listening": (45, 168, 255),
        "thinking": (179, 157, 255),
        "speaking": (150, 100, 255),
        "action": (91, 155, 255),
        "error": (255, 60, 90),
    },
)

PERSONAS: dict[str, Persona] = {p.key: p for p in (ALICIA, VERIS)}

_current: Persona = ALICIA


def current() -> Persona:
    return _current


def set_current(key: str) -> Persona:
    global _current
    _current = PERSONAS.get((key or "").strip().lower(), ALICIA)
    return _current
