# Alicia

Copilote IA gratuit pour Windows : Alicia regarde ce qui est affiché sur l’écran principal, répond aux questions et conseille. Elle ne joue jamais à votre place et ne génère ni touches ni clics.

Le parcours par défaut utilise **Ollama** pour la vision et le raisonnement, **Whisper local** pour reconnaître le français et **Kokoro** pour une voix neuronale féminine française (`ff_siwis`). Aucun compte, clé API ou abonnement n’est nécessaire. Il ne s’agit pas de cette conversation ChatGPT, et la voix ne reproduit pas une voix de ChatGPT.

![Interface Alicia](docs/assets/interface-demo.png)

## Installer ou mettre à jour

1. Extraire complètement la nouvelle archive dans un dossier.
2. Double-cliquer sur **Installer_Alicia.bat** et attendre la fin de la préparation.
3. Double-cliquer sur **Lancer_Alicia.bat**.

L’installation prépare Python 3.12, uv, Ollama, les dépendances verrouillées et les modèles locaux. Les téléchargements initiaux représentent plusieurs Go pour la vision et des modèles audio supplémentaires. L’installation conserve votre `.env` ; un ancien modèle Vosk ou une voix Windows ne sont plus les moteurs par défaut.

Les scripts PowerShell équivalents sont `scripts/setup_local.ps1` et `scripts/start_alicia.ps1`. Le lanceur impose le parcours gratuit pour ce processus, puis restaure les variables de la console. Il ne télécharge pas de modèle pendant le lancement ou une question. Voir [Installation gratuite](docs/INSTALLATION_GRATUITE.md).

## Parler à Alicia

Au lancement normal, **l’écran principal et le microphone démarrent automatiquement**, selon la demande de l’utilisateur. L’indicateur d’état montre l’écoute. Il n’est plus nécessaire de choisir une fenêtre ou d’appuyer sur Activer le micro.

Passez dans votre jeu ou votre navigateur, puis dites par exemple :

> « Alicia, décris ce que tu vois. »
>
> « Alicia, lequel de ces objets semble le plus adapté ? »

Laissez un silence en fin de question. Dire seulement « Alicia » ouvre aussi une fenêtre de huit secondes pour la phrase suivante. Les autres conversations sont ignorées. Alicia prend une capture fraîche, l’analyse localement puis lit sa réponse. Un historique court de la session aide les questions de suivi ; la capture actuelle reste prioritaire si l’écran a changé.

**Stop** coupe l’observation et l’écoute ; **Reprendre** les relance. L’écoute se suspend pendant le traitement et la lecture pour éviter qu’Alicia ne se réponde à elle-même, puis reprend. Cette version fonctionne par tours : l’interruption vocale pendant sa réponse n’est pas encore proposée.

L’aperçu est actualisé environ chaque seconde, sans demander une analyse IA à chaque image. Le délai de transcription, de chargement et d’inférence reste mesurable ; aucune réponse instantanée n’est promise. L’écran principal comprend tout son contenu visible : minimisez Alicia ou passez dans le jeu pour qu’elle voie ce contenu. Une source différente reste disponible dans les options avancées.

## Voix, contexte et recherche

Kokoro produit une voix française féminine neuronale locale. Son volume est réglable ; l’avatar s’anime pendant la lecture. Le rendu doit être écouté sur votre sortie audio, sans promettre la qualité ou le timbre exact de ChatGPT. Une image personnelle peut remplacer le portrait et reste locale.

Un [extrait de voix généré réellement](examples/voix-francaise.wav) est fourni pour écouter ce nouveau timbre. Sur le CPU du cloud, cet extrait de 8,37 secondes a été généré en 4,81 secondes au premier appel. Ces mesures ne prédisent pas la latence de votre jeu ou de votre PC.

Whisper remplace le petit modèle Vosk par défaut. Les noms propres, le bruit et les termes de jeu peuvent encore être mal reconnus. Le texte de la question reconnue reste visible pour le vérifier. Le contexte court aide le modèle à suivre l’échange, sans garantir qu’un « celui-là » ambigu sera résolu : Alicia doit alors demander une précision. Stop ou un changement de source efface ce contexte ; aucune mémoire de conversation n’est persistée.

La case **Autoriser la recherche web** est désactivée par défaut. Si vous l’autorisez, le moteur reçoit uniquement le texte de la question, sans image ni audio. Les extraits, liens et dates de récupération sont affichés comme sources. Une date de récupération n’est pas une date de publication ; les pages complètes ne sont pas lues dans ce premier adaptateur. Une erreur réseau ou un CAPTCHA est annoncé, sans repli payant ni fausse information récente.

## Vérifier le développement

Depuis la racine du dépôt :

```powershell
uv sync --python 3.12 --frozen --extra dev
uv run --frozen ruff check src tests
uv run --frozen ruff format --check src tests
uv run --frozen pytest -q
uv run --frozen alicia --smoke-test
```

La démonstration `uv run --frozen alicia --demo` utilise une image fictive et ne démarre pas automatiquement le microphone. Le smoke test reste hors écran, sans micro, analyse IA ou voix réelle. Les tests avec doubles ne remplacent pas les essais du micro, du jeu et des modèles sur Windows. Les résultats réellement exécutés doivent être rapportés séparément ; suivre [Validation Windows](docs/VALIDATION_WINDOWS.md).

Les logs tournants sont sous `%LOCALAPPDATA%/Alicia/logs`. Les captures, questions, transcriptions, réponses et flux audio ne sont pas enregistrés dans les logs par défaut. Les modèles sont installés sous `%LOCALAPPDATA%/Alicia/models`, hors du dépôt. Une CI Linux et Windows est définie dans `.github/workflows/checks.yml`.

Vérifications de cette version : 450 tests Python réussis, parcours graphique hors écran réussi et 6 scénarios/68 assertions PowerShell avec outils factices. La synthèse Kokoro a aussi réellement généré du français. Le téléchargement Whisper est refusé par le réseau du cloud (403) : la transcription réelle, le microphone et la capture de l’écran principal sous Windows restent à valider sur le PC cible.

## Documents

- [Installation gratuite](docs/INSTALLATION_GRATUITE.md).
- [Prompt complet Alicia](docs/PROMPT_PROJET_ALICIA.md).
- [Architecture](docs/architecture-v0.1.md).
- [Feuille de route](docs/ROADMAP.md).
- [Validation Windows](docs/VALIDATION_WINDOWS.md).
