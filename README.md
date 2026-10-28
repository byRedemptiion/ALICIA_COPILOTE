# Alicia

Copilote IA pour Windows : observer une fenêtre de jeu, comprendre une capture et conseiller le joueur. Alicia ne contrôle jamais le jeu.

**Le fonctionnement par défaut est local et gratuit à l’usage : aucune clé API, aucun abonnement.** Ollama exécute le modèle visuel `qwen2.5vl:7b` sur votre PC, Vosk transcrit vos questions au microphone et une voix française féminine de Windows lit les réponses. La recherche web est facultative et nécessite Internet. Aucun repli automatique vers un service payant.

![Interface Alicia avec avatar et inventaire de démonstration](docs/assets/interface-demo.png)

## Installer et lancer sous Windows

Dans le dossier du projet :

1. Double-cliquer sur **Installer_Alicia.bat** pour la première installation.
2. Une fois l’installation terminée, double-cliquer sur **Lancer_Alicia.bat**.

La fenêtre d’installation reste ouverte pour lire le résultat. Les lanceurs autorisent uniquement l’exécution du script pour ce processus PowerShell ; aucune politique globale n’est modifiée.

Les mêmes opérations sont disponibles depuis PowerShell :

```powershell
.\scripts\setup_local.ps1
.\scripts\start_alicia.ps1
```

L’installation prépare uv, Python, Ollama, les dépendances, le modèle visuel et le modèle français de reconnaissance vocale. Elle télécharge plusieurs Go une première fois, plus environ 41 Mo pour Vosk, et préserve votre `.env`. Le lanceur démarre Ollama si nécessaire, vérifie le modèle visuel et force les fournisseurs gratuits pour ce lancement ; aucun téléchargement de modèle ne commence pendant une question. Voir [le guide d’installation gratuite](docs/INSTALLATION_GRATUITE.md) pour les détails, les voix Windows et les éventuels blocages PowerShell.

Pour découvrir l’interface avec un inventaire fictif :

```powershell
.\scripts\start_alicia.ps1 -Demo
```

## Utiliser Alicia

Sélectionner une fenêtre, **Démarrer**, **Capturer**, vérifier l’aperçu, saisir une question puis demander l’analyse. La capture et la question sont traitées par Ollama sur votre PC. La démo affiche une image synthétique clairement identifiée ; elle n’invente pas de réponse IA.

Après une réponse, **Lire la réponse** lance la voix synthétique locale. Le volume est réglable et l’avatar s’anime pendant la lecture effective. Le ton féminin doux repose sur une voix française installée dans Windows, avec un débit ralenti ; le rendu doit être écouté sur la machine cible. Une image personnelle peut remplacer le portrait sans être envoyée au modèle.

Pour poser une question oralement : démarrer l’observation d’une fenêtre, autoriser l’analyse locale, sélectionner le microphone puis cliquer une fois sur **Activer le micro**. Dire **« Alicia, … »** suivi de la question, puis laisser un silence. On peut aussi dire seulement « Alicia », puis poser la question dans les huit secondes suivantes. Les phrases sans ce mot de réveil sont ignorées. Alicia prend une capture fraîche et lance l’analyse. **Réponse vocale automatique** permet d’entendre la réponse sans cliquer sur Lire. Le micro est suspendu pendant le traitement et la parole d’Alicia pour éviter de retranscrire sa propre voix ; **Couper le micro** ou **Arrêter** coupe l’écoute. Il reste désactivé au lancement et aucun fichier audio du micro n’est enregistré.

Avec **Vision locale en continu** cochée, l’aperçu de la fenêtre sélectionnée est actualisé environ une fois par seconde tant que l’observation est active. Cette actualisation reste locale : elle ne lance pas une analyse IA à chaque image. Une question vocale déclenche sa propre capture récente. « Temps réel » décrit ici cette actualisation ; la transcription et le calcul du modèle ajoutent leur latence.

Pour rechercher une information actuelle, cocher **Autoriser la recherche web** avant la question. Seul son texte est envoyé au moteur DuckDuckGo ; l’image, le portrait et l’audio restent locaux. Les titres, extraits et liens trouvés sont joints au contexte du modèle et affichés comme sources consultables. La date de récupération ne prouve pas la date de publication ni l’actualité d’un extrait. Un moteur indisponible, une limite ou un CAPTCHA donne une erreur explicite ; Alicia ne doit pas présenter une recherche échouée comme une information récente vérifiée.

La conversation vocale reste organisée en tours : appeler Alicia, poser la question, attendre le traitement puis la réponse. L’interruption vocale pendant la lecture, l’analyse IA permanente de la vidéo et la mémoire persistante ne sont pas incluses. PrintWindow peut échouer sur certains jeux et modes plein écran. La compatibilité du jeu, du microphone, la charge GPU, la qualité des réponses et le rendu vocal nécessitent des essais sur votre PC.

## Développer et vérifier

Prérequis : Python 3.12 et uv. Depuis la racine du dépôt :

```powershell
uv sync --python 3.12 --frozen --extra dev
uv run --frozen pytest
uv run --frozen alicia --smoke-test
uv run --frozen ruff check src tests
```

Contrôles effectués dans le cloud : **314 tests Python réussis**, dont le parcours vocal avec doubles et un échange HTTP local ; **6 scénarios et 61 assertions PowerShell réussis** avec outils factices ; contrôle Ruff et parcours graphique hors écran réussis.

Le smoke test vérifie le parcours graphique hors écran, sans modèle ni voix réellement exécutés. Ces tests ne valident pas un vrai jeu Windows. La capture native, le microphone, Vosk sur une vraie phrase, le modèle sur GPU et la voix SAPI doivent être vérifiés sur la machine cible. Le réseau cloud a refusé le téléchargement vocal et la recherche web réelle (403) ; les domaines nécessaires sont enregistrés dans le brouillon de configuration, sans preuve d’application au runtime courant.

Le test PowerShell portable vérifie notamment que l’installation prépare explicitement Vosk, qu’un échec de préparation n’est pas présenté comme un succès et que le lancement ne télécharge aucun modèle. Ces contrôles avec outils factices ne constituent pas une installation native Windows.

Les logs tournants sont stockés sous `%LOCALAPPDATA%/Alicia/logs`. Les captures, questions, transcriptions, réponses et flux audio ne sont pas enregistrés dans les logs par défaut. Le modèle Vosk est installé sous `%LOCALAPPDATA%/Alicia/models`, hors du dépôt. La configuration `.env` est facultative et exclue de Git. Un ancien fichier contenant une clé OpenAI n’est pas nécessaire au mode gratuit.

Une CI Linux et Windows est définie dans `.github/workflows/checks.yml` ; elle sera exécutée après envoi du dépôt. Les adaptateurs OpenAI historiques restent disponibles seulement sur choix explicite et peuvent être facturés ; ils ne font pas partie du parcours gratuit décrit ici.

## Documents

- [Installation gratuite](docs/INSTALLATION_GRATUITE.md).
- [Prompt complet Alicia](docs/PROMPT_PROJET_ALICIA.md), avec gratuité, avatar et voix féminine douce.
- [Architecture V0.1](docs/architecture-v0.1.md).
- [Feuille de route](docs/ROADMAP.md).
- [Validation Windows](docs/VALIDATION_WINDOWS.md).
