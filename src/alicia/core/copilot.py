"""Mode Copilote : le robot jette un coup d'œil à l'écran et ne parle que si ça compte.

À chaque coup d'œil, le cerveau rapide répond par un petit JSON :
``{"speak": true, "importance": 8, "message": "…", "reason": "…"}``.
Le robot ne parle que si l'importance atteint le seuil, que le délai de silence
(cooldown) est passé, et que ce n'est pas une redite. Il observe et conseille :
il n'agit jamais dans le jeu.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
import time
from collections import deque
from dataclasses import dataclass

from alicia.core.ai.base import AnalysisRequest, PreparedImage, VisionModel
from alicia.core.ai.prompts import build_system_prompt
from alicia.core.persona import current as current_persona

log = logging.getLogger("alicia.copilot")

COPILOT_QUESTION = "Coup d'œil du mode Copilote : faut-il dire quelque chose maintenant ?"

COPILOT_RULES = """
MODE COPILOTE — personne ne t'a posé de question. Tu regardes l'écran pour décider s'il
vaut la peine de parler MAINTENANT. Par défaut, tu te tais.
Réponds UNIQUEMENT par un objet JSON sur une seule ligne, sans texte autour :
{{"speak": true ou false, "importance": 1 à 10, "message": "...", "reason": "..."}}
- 9-10 : danger immédiat, erreur grave en cours, objectif perdu si rien n'est fait.
- 7-8 : vraie opportunité ou conseil utile tout de suite.
- 1-6 : anecdotique, rien de neuf, déjà dit → "speak": false.
- Menu, écran de chargement, pause, bureau, cinématique : "speak": false.
- "message" : une phrase courte à dire à voix haute (20 mots maximum), sans markdown ;
  vide si "speak" est false. "reason" : quelques mots pour le journal.
- Tu conseilles seulement : tu ne joues jamais à la place du joueur.
{recent}"""


@dataclass(frozen=True)
class Decision:
    speak: bool
    importance: int
    message: str
    reason: str = ""


def parse_decision(text: str) -> Decision | None:
    """Lit le JSON du modèle (tolère du texte ou des ``` autour). None si illisible."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if match is None:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        importance = max(0, min(10, int(float(data.get("importance", 0)))))
    except (TypeError, ValueError):
        importance = 0
    message = str(data.get("message") or "").strip()
    speak = data.get("speak")
    speak = speak.strip().lower() in ("true", "oui", "1") if isinstance(speak, str) else bool(speak)
    return Decision(
        speak and bool(message), importance, message[:300], str(data.get("reason") or "")[:200]
    )


class CopilotGate:
    """Seuil d'importance, délai de silence et anti-redite."""

    def __init__(self, threshold: int = 7, cooldown_s: float = 60.0) -> None:
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.last_spoken_at: float | None = None
        self.recent: deque[str] = deque(maxlen=5)

    def allow(self, decision: Decision, now: float | None = None) -> tuple[bool, str]:
        now = time.monotonic() if now is None else now
        if not decision.speak:
            return False, "rien d'important"
        if decision.importance < self.threshold:
            return False, f"importance {decision.importance} < seuil {self.threshold}"
        if decision.importance < 9 and self.last_spoken_at is not None:
            left = self.cooldown_s - (now - self.last_spoken_at)
            if left > 0:
                return False, f"délai de silence ({left:.0f} s restantes)"
        said = decision.message.casefold()
        for old in self.recent:
            if difflib.SequenceMatcher(None, said, old.casefold()).ratio() >= 0.75:
                return False, "déjà dit"
        return True, "urgent" if decision.importance >= 9 else "utile"

    def spoke(self, message: str, now: float | None = None) -> None:
        self.last_spoken_at = time.monotonic() if now is None else now
        self.recent.append(message)

    def recent_note(self) -> str:
        if not self.recent:
            return ""
        lines = "\n".join(f"- {m}" for m in self.recent)
        return f"Déjà dit récemment (ne le répète pas) :\n{lines}"


class Copilot:
    def __init__(self, gate: CopilotGate | None = None) -> None:
        self.gate = gate or CopilotGate()

    def observe(
        self, model: VisionModel, image: PreparedImage, game_context: str = ""
    ) -> tuple[Decision | None, bool, str]:
        """Un coup d'œil : (décision, parler ?, raison). Ne lève pas pour une réponse illisible."""
        request = AnalysisRequest(
            question=COPILOT_QUESTION,
            images=(image,),
            system_prompt=build_system_prompt(
                game_context + COPILOT_RULES.format(recent=self.gate.recent_note()),
                spoken=True,
                brain="rapide",
            ),
            max_output_tokens=200,
            temperature=0.3,
        )
        started = time.perf_counter()
        result = model.analyze(request)
        took = int((time.perf_counter() - started) * 1000)
        decision = parse_decision(result.text)
        title = current_persona().title
        if decision is None:
            log.info(
                "[%s] [Cerveau rapide] [Copilote] %s/%s — réponse illisible (%d ms)",
                title,
                model.provider,
                model.model,
                took,
            )
            return None, False, "réponse illisible"
        speak, why = self.gate.allow(decision)
        log.info(
            "[%s] [Cerveau rapide] [Copilote] %s/%s — importance %d/10 → %s (%s) en %d ms%s",
            title,
            model.provider,
            model.model,
            decision.importance,
            "parle" if speak else "se tait",
            why,
            took,
            f" — {decision.reason}" if decision.reason else "",
        )
        if speak:
            self.gate.spoke(decision.message)
        return decision, speak, why
