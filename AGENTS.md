# Développer Alicia

Alicia est un copilote visuel Windows : observation et conseil uniquement, sans contrôle du jeu. Le cahier des charges de référence est `docs/PROMPT_PROJET_ALICIA.md`.

Exigence utilisateur : fonctionnement gratuit par défaut, sans clé API. Utiliser Ollama en loopback avec un modèle local multimodal et la voix Windows française féminine. Ne jamais ajouter de repli automatique vers un service payant. Les téléchargements de modèles se font explicitement pendant l’installation, pas lors d’une analyse.

## Travailler dans le dépôt

- Utiliser le checkout existant. Chaque tâche cloud est déjà isolée ; ne pas créer de worktree sans demande.
- Python 3.12, code sous `src/alicia`, dépendances gérées avec uv. Préserver le verrouillage et l’actualiser lorsqu’une dépendance change.
- Le cœur ne dépend ni de Qt, ni de Win32, ni du SDK IA. Les adaptateurs implémentent ses contrats.
- Pas de travail bloquant sur le thread Qt. Concurrence bornée et rejet des résultats périmés après arrêt.
- Ne jamais journaliser de clé, image, question, réponse ou erreur brute du SDK. Le portrait choisi reste local.
- Micro désactivé au lancement ; écoute locale uniquement après activation. « Alicia » déclenche une question, une capture fraîche et une réponse. Suspendre la reconnaissance pendant les traitements et la lecture pour éviter l’écho.
- L’aperçu continu capture localement la fenêtre sélectionnée sans appeler l’IA à chaque image. Les appels IA restent déclenchés par une question ou une action du joueur.
- Recherche Internet seulement après autorisation dans l’interface. Envoyer la question, jamais l’image ou l’audio, au moteur gratuit ; afficher les sources et distinguer date de récupération et de publication.

## Vérifier

Depuis la racine :

```text
uv sync --frozen --extra dev
uv run --frozen ruff check src tests
uv run --frozen ruff format --check src tests
uv run --frozen pytest -q
uv run --frozen alicia --smoke-test
```

Dans le cloud, utiliser si nécessaire `UV_CACHE_DIR=/workspace/.cache/uv`, `XDG_CACHE_HOME=/workspace/.cache` et `XDG_STATE_HOME=/workspace/.alicia-state` pour les caches et logs locaux.

Les tests hors écran utilisent des adaptateurs factices. Ne pas les présenter comme des captures de jeu ou des appels API réels. Suivre `docs/VALIDATION_WINDOWS.md` pour la capture native et l’écoute sur la machine cible. Ne pas intégrer de clé dans un fichier suivi ou un rapport.
