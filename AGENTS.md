# Développer Alicia

Alicia est un copilote Windows qui observe et conseille sans contrôler le jeu. Le cahier des charges de référence est `docs/PROMPT_PROJET_ALICIA.md`.

Exigences utilisateur actuelles : fonctionnement gratuit uniquement, voix française féminine plus expressive, reconnaissance locale plus précise, écran principal et microphone actifs au lancement, terminal masqué et icône arrondie issue de l’image fournie. L’utilisateur autorise désormais ces modifications et « Alicia, stop » pendant la parole. Ces demandes remplacent les anciennes règles de lancement manuel et d’absence d’interruption. Stop coupe l’observation et l’écoute ; Reprendre les relance. La commande vocale coupe seulement la voix.

## Travailler dans le dépôt

- Utiliser le checkout existant. Chaque tâche cloud est isolée ; ne pas créer de worktree sans demande.
- Python 3.12, code sous `src/alicia`, dépendances uv verrouillées. Actualiser le verrouillage lorsqu’une dépendance change.
- Le cœur reste indépendant de Qt, Win32 et des SDK des fournisseurs.
- Utiliser Ollama loopback avec qwen3-vl:8b, faster-whisper large-v3-turbo multilingue et Chatterbox Multilingual local par défaut. Chatterbox utilise sa propre installation Python ; Kokoro reste un choix explicite plus léger. Aucun repli automatique vers un service payant, et aucune intégration à la session ChatGPT du joueur.
- Les téléchargements de modèles se font explicitement pendant l’installation, jamais au lancement ou pendant une question. Le lanceur normal VBS utilise pythonw et garde les erreurs visibles par dialogue ; le lanceur Debug conserve la console.
- Le thread Qt ne fait aucun travail bloquant. Concurrence bornée et résultats périmés ignorés après Stop, changement de source ou retrait d’autorisation.
- L’écoute démarre avec le mode normal et un état visible, puis attend « Alicia ». La démonstration et le smoke test n’ouvrent pas le micro. Suspendre l’écoute ordinaire pendant le traitement ; pendant la lecture réelle, reconnaître seulement « Alicia, stop ». Prévenir les auto-déclenchements sans promettre une annulation d’écho complète ou une interruption instantanée.
- L’aperçu de l’écran principal est local et périodique. Une question déclenche une capture fraîche ; aucune analyse IA à chaque image.
- Conserver un contexte de conversation court et borné en mémoire uniquement. L’écran actuel prime et Stop efface la mémoire.
- La recherche web demande une autorisation dans l’interface. Envoyer la question seulement, jamais image ou audio ; afficher sources et distinguer dates de récupération et publication.
- Ne jamais journaliser clé, image, question, transcription, réponse ou erreur brute de fournisseur. Le portrait personnel reste local.

## Vérifier

Depuis la racine :

```text
uv sync --frozen --extra dev
uv run --frozen ruff check src tests
uv run --frozen ruff format --check src tests
uv run --frozen pytest -q
uv run --frozen alicia --smoke-test
```

Dans le cloud, utiliser si nécessaire `UV_CACHE_DIR=/workspace/.cache/uv`, `XDG_CACHE_HOME=/workspace/.cache` et `XDG_STATE_HOME=/workspace/.alicia-state`.

Les tests hors écran utilisent des doubles ; ne pas les présenter comme des essais matériels ou des modèles réels. Utiliser un `QApplication` unique dans les tests et détruire les widgets sur le thread graphique. Suivre `docs/VALIDATION_WINDOWS.md` pour le lancement masqué, l’icône, l’écran principal, le micro, Whisper turbo, Chatterbox, l’interruption et le jeu. Aucun résultat non exécuté ne doit être déclaré réussi.
