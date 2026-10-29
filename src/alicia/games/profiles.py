"""Profils de jeu : contexte ajouté au prompt, sans toucher au moteur d'Alicia.

Un profil pourra plus tard fournir des zones d'écran (HUD, inventaire) et des connaissances.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from alicia.core.capture.models import WindowInfo


@dataclass(frozen=True)
class GameProfile:
    key: str
    name: str
    exe_names: tuple[str, ...] = ()
    title_keywords: tuple[str, ...] = ()
    context: str = ""
    regions: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)

    def matches(self, window: WindowInfo) -> bool:
        exe = window.exe_name.casefold()
        title = window.title.casefold()
        return exe in self.exe_names or any(k in title for k in self.title_keywords)


GENERIC = GameProfile(key="generic", name="Jeu générique")

OVERWATCH = GameProfile(
    key="overwatch",
    name="Overwatch",
    exe_names=("overwatch.exe",),
    title_keywords=("overwatch",),
    context="""\
Le jeu est Overwatch (FPS en équipe, héros répartis en rôles tank, dégâts et soutien).
- Identifie le héros du joueur à partir de son HUD (portrait, capacités, arme) avant de conseiller.
- En mode Stadium, le joueur achète entre les manches des objets et des pouvoirs avec une \
monnaie : compare les cartes visibles selon le héros, leur texte lisible et leur coût.
- Les valeurs d'équilibrage changent à chaque saison : ne cite que les chiffres lisibles \
à l'écran, et dis-le si tu t'appuies sur un souvenir général.""",
)

PROFILES: dict[str, GameProfile] = {p.key: p for p in (GENERIC, OVERWATCH)}


def resolve_profile(window: WindowInfo | None, setting: str = "auto") -> GameProfile:
    if setting != "auto":
        return PROFILES.get(setting, GENERIC)
    if window is not None:
        for profile in PROFILES.values():
            if profile is not GENERIC and profile.matches(window):
                return profile
    return GENERIC
