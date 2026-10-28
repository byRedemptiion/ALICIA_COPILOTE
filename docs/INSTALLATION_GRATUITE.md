# Alicia — Installation locale gratuite sous Windows

Alicia utilise par défaut **Ollama et le modèle visuel local `qwen2.5vl:7b`**, Vosk pour comprendre les questions au microphone et une voix féminine française de Windows. Aucun abonnement, crédit API ou compte OpenAI n’est nécessaire. Les calculs utilisent votre PC ; les téléchargements initiaux nécessitent Internet et plusieurs Go d’espace disque. La recherche web facultative utilise Internet après autorisation, sans clé API. La consommation électrique et les ressources de la machine restent à votre charge.

## Installation guidée

Dans le dossier du projet, double-cliquer sur **Installer_Alicia.bat**. Attendre la fin et lire le résultat avant de fermer la fenêtre. Après installation, **Lancer_Alicia.bat** ouvre Alicia. Ces deux fichiers appellent les scripts PowerShell du dossier `scripts` et ne modifient pas la politique d’exécution globale.

Pour effectuer l’installation depuis une console, ouvrir PowerShell dans le dossier du projet, puis lancer :

```powershell
.\scripts\setup_local.ps1
```

Le script utilise `winget` pour installer les outils manquants `uv` et Ollama depuis leurs paquets habituels, démarre le service Ollama local si nécessaire, télécharge `qwen2.5vl:7b` s’il manque et installe les dépendances Python verrouillées. Il appelle ensuite `uv run --frozen alicia --prepare-voice` pour préparer le modèle français de Vosk. `uv` prépare Python 3.12 si nécessaire. Le script n’écrase ni ne crée de `.env` et conserve les fichiers utilisateur. Un échec de préparation vocale est signalé ; ne pas considérer cette installation comme terminée tant qu’il n’est pas résolu.

Le téléchargement du modèle peut représenter environ 6 Go selon la version ; consulter [sa fiche Ollama](https://ollama.com/library/qwen2.5vl:7b) pour la taille actuelle. Le premier chargement est plus lent que les analyses suivantes. Le script peut être relancé : un modèle déjà présent n’est pas téléchargé à nouveau.

Le modèle [Vosk français léger](https://alphacephei.com/vosk/models) `vosk-model-small-fr-0.22` représente environ 41 Mo. Il est récupéré sur le site officiel en HTTPS avec vérification TLS, puis son archive ZIP est contrôlée avant extraction sous `%LOCALAPPDATA%/Alicia/models/vosk-model-small-fr-0.22`. Le SHA256 calculé à réception est une trace du téléchargement ; il ne constitue pas une vérification contre une empreinte indépendante publiée par l’éditeur. Aucun checksum officiel non vérifié n’est inventé. Le modèle n’est pas téléchargé lorsqu’on active le micro ou pose une question.

Si PowerShell refuse ce script local en raison de sa politique d’exécution, l’inspecter avant de l’autoriser pour ce seul lancement :

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_local.ps1
```

Cette commande n’altère pas la politique globale de la machine et ne désactive ni TLS, ni la vérification des paquets. Si `winget` est absent, installer ou mettre à jour **App Installer** depuis Microsoft Store puis relancer. Une politique d’entreprise peut nécessiter l’intervention de l’administrateur ; le script ne la contourne pas.

## Lancer Alicia

Double-cliquer sur **Lancer_Alicia.bat**, ou lancer depuis PowerShell :

```powershell
.\scripts\start_alicia.ps1
```

Ou, avec une capture fictive pour découvrir l’interface :

```powershell
.\scripts\start_alicia.ps1 -Demo
```

Le lanceur redémarre Ollama si nécessaire et vérifie le modèle avant d’ouvrir Alicia. Il ne lance pas de téléchargement volumineux. Il force les fournisseurs gratuits, le modèle `qwen2.5vl:7b` et l’URL locale pour ce lancement, y compris lorsqu’un ancien `.env` contient une sélection OpenAI, et restaure ensuite les variables de la console. Les scripts communiquent uniquement avec `127.0.0.1:11434`. Un serveur Ollama lancé par eux reçoit `OLLAMA_NO_CLOUD=1` ; cette variable ne reconfigure pas un serveur déjà démarré.

Dans Alicia : sélectionner une fenêtre, **Démarrer**, **Capturer**, saisir une question, autoriser l’analyse puis cliquer sur **Analyser la capture**. L’image et la question sont traitées par Ollama sur votre PC. **Lire la réponse** utilise la synthèse Windows locale, sans envoyer le texte à un service vocal. L’avatar s’anime durant la lecture effective.

## Parler à Alicia

1. Démarrer l’observation d’une fenêtre et autoriser son analyse locale.
2. Sélectionner le microphone voulu puis cliquer sur **Activer le micro**. Autoriser l’accès aux applications de bureau dans les paramètres de confidentialité Windows si nécessaire.
3. Dire « Alicia » suivi de la question en français, puis laisser un silence. On peut dire « Alicia » seule, puis poser la question dans les huit secondes suivantes. Les autres phrases sont ignorées. Le texte de la question reconnue apparaît dans Alicia ; une nouvelle capture est prise pour cette question.
4. Garder **Réponse vocale automatique** activée pour entendre la réponse dès qu’elle est prête. La lecture manuelle reste disponible.
5. Cliquer sur **Couper le micro** pour terminer l’écoute. **Arrêter** l’observation la coupe aussi.

L’écoute n’est jamais active au lancement. Après activation, l’état indique l’attente du mot « Alicia » ; il n’est plus nécessaire de cliquer avant chaque question. Le micro est suspendu pendant traitement d’une question et lecture pour éviter les boucles et les questions empilées. Après une erreur, vérifier le message et reprendre explicitement ; aucune relance automatique ne doit masquer une panne. Cette première conversation fonctionne en tours, sans interruption par la voix pendant qu’Alicia parle. La qualité de transcription et de détection du nom doit être testée avec le bruit réel du jeu.

**Vision locale en continu** actualise l’aperçu de la seule fenêtre sélectionnée environ une fois par seconde pendant l’observation. Cette option est cochée par défaut et peut être désactivée. Elle ne capture pas silencieusement tout le bureau et ne lance pas une analyse IA pour chaque image. Une question déclenche une capture récente ; l’actualisation, la transcription puis le calcul du modèle ont chacun leur latence.

Pour préparer seulement le modèle vocal après une mise à jour :

```powershell
uv run --frozen alicia --prepare-voice
```

Cette commande peut télécharger le modèle ; elle ne démarre pas l’écoute. L’audio du micro est traité localement et n’est pas sauvegardé ou envoyé au moteur de recherche.

## Rechercher une information actuelle

Cocher **Autoriser la recherche web** avant de poser la question. Seul son texte est envoyé à DuckDuckGo. Les titres, extraits et liens obtenus sont fournis au modèle puis affichés comme sources cliquables. Cette version consulte les résultats du moteur ; elle ne lit pas intégralement les pages liées.

Internet est nécessaire pour cette option. Les moteurs gratuits peuvent limiter les requêtes ou afficher un CAPTCHA. Alicia doit signaler cet échec et ne pas prétendre avoir trouvé une information actuelle. Vérifier les sources, la version du jeu et les dates : la date de récupération n’est pas une date de publication. Décocher l’option évite cette recherche ; l’analyse locale et la voix restent utilisables hors ligne après installation.

## Voix féminine douce

Le premier moteur local utilise les voix SAPI installées dans Windows. Il choisit une voix **française et féminine**, avec un débit légèrement ralenti ; il ne remplace pas silencieusement cette voix par une voix masculine ou anglaise. `Microsoft Hortense Desktop` est préférée lorsqu’elle est présente. Ce premier moteur n’est pas neuronal : la qualité dépend des voix installées et doit être écoutée sur votre PC ; il ne promet pas le naturel d’un service neuronal distant.

Si aucune voix compatible n’est disponible, ouvrir **Paramètres Windows → Heure et langue → Voix**, ajouter le français et ses composants vocaux, puis relancer Alicia. Le chemin exact varie selon la version de Windows. Certaines voix « naturelles » proposées par Windows ne sont pas exposées à SAPI ; installer une voix disponible pour les applications de bureau.

Options facultatives dans `.env` :

```dotenv
ALICIA_AI_PROVIDER=ollama
ALICIA_OLLAMA_MODEL=qwen2.5vl:7b
ALICIA_OLLAMA_URL=http://127.0.0.1:11434
ALICIA_TTS_PROVIDER=windows
ALICIA_WINDOWS_VOICE=
ALICIA_WINDOWS_RATE=-1
```

Laisser le nom de voix vide pour la sélection automatique. Pour en imposer une, renseigner son nom exact tel qu’installé. Aucun de ces paramètres n’est une clé secrète. Les valeurs par défaut suffisent ; aucun `.env` n’est obligatoire.

## Installation manuelle

Installer [uv](https://docs.astral.sh/uv/getting-started/installation/) et [Ollama pour Windows](https://ollama.com/download/windows), puis lancer :

```powershell
ollama pull qwen2.5vl:7b
uv sync --python 3.12 --frozen --extra dev
uv run --frozen alicia --prepare-voice
uv run --frozen alicia
```

Ollama doit fonctionner en arrière-plan sur le port local 11434. Le modèle téléchargé est utilisable hors ligne ensuite. Le mode gratuit ne bascule jamais automatiquement vers OpenAI si Ollama, le modèle ou la voix manque. Un ancien `OPENAI_API_KEY` peut être retiré de votre `.env` : il n’est pas utilisé par les fournisseurs gratuits.

## Diagnostic et limites

- **Ollama inaccessible** : ouvrir Ollama et relancer le lanceur ; vérifier le service local sur le port 11434.
- **Modèle absent** : relancer `setup_local.ps1`. Pour utiliser un autre modèle local compatible image, le télécharger explicitement avec `ollama pull`, le choisir dans `.env`, puis lancer directement `uv run --frozen alicia` ; les scripts imposent le modèle par défaut.
- **Première analyse lente** : laisser finir le chargement du modèle avant de juger sa latence. Mesurer la charge GPU et la fluidité du jeu ensemble.
- **Voix absente** : installer une voix SAPI française féminine ; l’analyse visuelle reste indépendante de la voix.
- **Modèle de reconnaissance absent** : relancer `Installer_Alicia.bat` ou `uv run --frozen alicia --prepare-voice`. L’activation du micro ne lance pas de téléchargement caché.
- **Microphone indisponible** : vérifier le périphérique sélectionné, les autorisations Windows et qu’une autre application ne bloque pas l’entrée. Couper le micro puis le réactiver après correction.
- **Recherche web indisponible ou limitée** : lire l’erreur et réessayer plus tard ; aucune API payante n’est appelée en secours. Les résultats ne prouvent pas qu’une source est à jour.
- **Micro coupé après une erreur** : corriger la cause indiquée, puis cliquer à nouveau sur Activer le micro. Aucun appel ni reprise d’écoute n’est relancé en boucle après un échec.
- **Capture noire ou figée** : essayer le mode fenêtré ou sans bordure, puis suivre [la procédure Windows](VALIDATION_WINDOWS.md). Certains jeux restent incompatibles avec PrintWindow.

Les tests automatisés du cloud vérifient les contrats et erreurs avec des doubles. Ils ne remplacent ni un vrai calcul du modèle sur votre GPU, ni une capture native du jeu, ni une transcription depuis votre micro, ni l’écoute de votre sortie audio. Les scripts PowerShell et l’intégration SAPI doivent être validés sur Windows. Un moteur de recherche bloqué dans le cloud n’établit pas qu’il sera indisponible sur votre PC, et l’inverse est également vrai.
