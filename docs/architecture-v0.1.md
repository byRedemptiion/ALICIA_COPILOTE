# Alicia — Architecture du socle et extensions vocales/web

## Périmètre

Le socle permet de lister les fenêtres Windows, sélectionner une fenêtre, démarrer et arrêter l’observation, capturer manuellement sa zone cliente, afficher un aperçu, envoyer cette image avec une question texte et afficher la réponse multimodale. L’extension ajoute une transcription locale au micro, une capture fraîche par question orale, une réponse vocale automatique optionnelle et une recherche web autorisée avec sources visibles. Les événements et erreurs sont horodatés ; les capacités natives restent à valider sous Windows.

Alicia observe et conseille. Elle ne produit ni touches ni clics, ne lit pas la mémoire du jeu et ne contourne aucune protection.

Hors périmètre actuel : analyse IA permanente d’un flux vidéo, détection autonome de changements, interruption pendant la parole d’Alicia, mémoire persistante et overlay. La conversation actuelle fonctionne par tours avec le mot de réveil « Alicia » et une écoute suspendue pendant le traitement des questions.

## Technologies proposées

- Python 3.12 pour un prototype modulaire et testable ; uv pour verrouiller les dépendances.
- PySide6 pour l’interface Windows, l’aperçu et les signaux entre workers et interface.
- API Win32 via ctypes pour énumérer les fenêtres et essayer PrintWindow comme premier backend de capture. Valider ce choix sur le jeu cible avant de poursuivre ; évaluer Windows Graphics Capture si nécessaire.
- Ollama local avec `qwen2.5vl:7b` comme adaptateur multimodal par défaut, accessible par HTTP sur la boucle locale uniquement. HTTPX envoie une image PNG et la question à `/api/chat`, sans flux vidéo ni repli distant.
- Synthèse vocale Windows SAPI pour une voix française féminine sans service payant. Les adaptateurs historiques OpenAI restent isolés et nécessitent une sélection explicite.
- Vosk et sounddevice pour la transcription française sur le PC. L’installation explicite prépare le modèle léger ; l’écoute n’effectue aucun téléchargement.
- Recherche DuckDuckGo par HTTPX avec résultats bornés et parser HTML. Seul le texte de la question quitte le PC lorsque l’option web est autorisée ; aucune page de destination n’est chargée dans ce premier adaptateur.
- logging standard avec rotation des fichiers et pytest pour les tests du cœur.

Le cloud Linux pourra tester le cœur. La capture native, le rendu Qt sous Windows et le futur exécutable nécessitent des essais Windows. PyInstaller sera évalué après validation de la V0.1.

## Arborescence cible

À créer progressivement, sans modules vides destinés à des fonctions lointaines :

```text
pyproject.toml
uv.lock
.env.example
src/alicia/
  __main__.py
  bootstrap.py
  config.py
  logging_config.py
  core/
    models.py
    ports.py
    capture_service.py
    analysis_service.py
    session.py
  capture/
    win32.py
    isolated.py
    demo.py
  ai/
    ollama_provider.py
    openai_provider.py
    prompts.py
  audio/
    windows_speech.py
    listening.py
    openai_speech.py
  research/
    search.py
  ui/
    main_window.py
    avatar.py
    playback.py
    workers.py
tests/
  unit/
  integration/
docs/
```

## Contrats et flux

L’interface appelle les services du cœur ; seuls les adaptateurs connaissent Win32 ou le SDK IA. Le point d’entrée assemble les composants.

```text
Fenêtre choisie → service capture → image figée → aperçu
Image figée + question → service analyse → fournisseur IA → réponse
Micro activé → Vosk local → « Alicia » + question → capture fraîche → analyse → voix
Question + autorisation web → moteur de recherche → sources → contexte d’analyse
```

- WindowSource.list_windows() retourne les fenêtres visibles avec leur identifiant et leur titre ; exclure Alicia et revérifier l’identité avant capture.
- CaptureSource.capture(window) retourne une image indépendante des ressources natives, ses dimensions, son horodatage et son identifiant.
- VisionProvider.analyze(request) reçoit l’image, la question et les sources obtenues si la recherche est autorisée, puis retourne texte, sources et métadonnées de durée sans exposer les objets du SDK.
- WebSource conserve titre, URL, extrait et date de récupération ; celle-ci n’est pas une date de publication.
- Session conserve uniquement la sélection, la dernière capture et le résultat courant. Une génération de session permet d’ignorer les résultats obsolètes après arrêt ou changement de fenêtre.

La mémoire et les futurs modules games/ ne modifieront pas les responsabilités des adaptateurs existants.

L’adaptateur de synthèse reçoit le texte d’une réponse après action explicite du joueur. Le moteur Windows utilise System.Speech via un processus PowerShell à délai borné ; le texte est transmis par l’entrée standard JSON, jamais interpolé dans la commande. Il retourne des octets WAV ; le lecteur Qt écrit et gère le fichier temporaire nécessaire à la lecture. Le portrait n’est jamais joint à la requête d’analyse ou de synthèse.

## Interface et exécution

Une fenêtre : liste actualisable, Démarrer, Arrêter, Capturer, aperçu, question, Analyser, réponse, sources et journal utilisateur. Le micro possède un sélecteur, Activer le micro/Couper le micro et un indicateur d’écoute. Réponse vocale automatique et Autoriser la recherche web sont des choix visibles ; le web est désactivé par défaut.

La capture et l’appel réseau s’exécutent hors du thread graphique. Les widgets ne sont modifiés que par les signaux Qt. Une seule capture et une seule analyse peuvent être en cours ; aucune file non bornée. Analyser exige une image et une question et utilise exactement l’image de l’aperçu au moment du clic.

Le mode vocal exige une observation active et l’autorisation d’analyse locale. Vosk fournit une phrase finale après silence. Le filtre de réveil attend « Alicia » suivi d’une question, ou « Alicia » seule puis une phrase dans les huit secondes ; les autres paroles sont ignorées. Le contrôleur prend alors une capture récente et utilise le même parcours que l’entrée texte. Pendant le traitement de la question et la lecture, l’écoute est suspendue et ses buffers sont invalidés pour empêcher les boucles et les questions empilées. L’arrêt coupe le micro, invalide les callbacks tardifs et empêche une réponse ancienne d’être prononcée. Une erreur demande une reprise explicite.

Un timer Qt actualise l’aperçu de la fenêtre sélectionnée environ une fois par seconde lorsque Vision locale en continu est cochée et l’observation active. Il ne remplit pas de queue et ne lance pas d’analyse IA pour chaque image. Cette capture locale périodique et la capture fraîche déclenchée par une question restent distinctes. L’actualisation visuelle ne promet pas une latence nulle pour la transcription ou le modèle.

Le flux PCM du micro transite par une queue bornée dans un worker et n’est jamais enregistré. Les modules Vosk/sounddevice et leurs erreurs ne doivent pas empêcher le démarrage du parcours texte. Un modèle manquant signale la commande d’installation ; il n’est pas téléchargé par le worker.

Les appels locaux ont un délai maximal. Arrêter invalide les résultats en cours sans promettre l’annulation d’un calcul déjà lancé dans Ollama. La fermeture demande l’arrêt des workers et utilise une attente bornée. Aucun échec ne déclenche d’appel vers un service payant.

## Avatar et lecture vocale

Un avatar vectoriel léger donne une identité à Alicia sans dépendre d’un service externe. L’utilisateur peut choisir une image locale. Le visuel exprime repos, capture, analyse et erreur.

La lecture est déclenchée par Lire la réponse ou, pour le parcours vocal, par Réponse vocale automatique lorsqu’elle est activée. Le moteur Windows sélectionne une voix française féminine installée et ralentit légèrement son débit. `Microsoft Hortense Desktop` est préférée lorsqu’elle est disponible. Une voix manquante produit une explication claire ; aucune sélection silencieuse d’une voix masculine ou anglaise. La qualité doit être écoutée sur Windows, sans promettre le rendu d’un moteur neuronal distant.

Qt Multimedia joue le WAV temporaire avec volume réglable. L’état parlant de l’avatar suit `QMediaPlayer.PlayingState`, puis s’arrête sur fin, arrêt ou erreur. Il s’agit d’une animation d’activité, pas d’une synchronisation phonétique. Libérer le média et supprimer le fichier temporaire à la fin. Signaler clairement que la voix est synthétique.

Les essais factices valident les contrats et erreurs sans périphérique audio ; ils ne prouvent pas que la synthèse native ou la sortie audio Windows fonctionne. L’écoute sur Windows reste une vérification distincte.

## Recherche web

La recherche est désactivée par défaut. Une activation envoie la question au moteur gratuit DuckDuckGo, avec délais, volume reçu et nombre de résultats bornés. Les sources contiennent titres, extraits et URL validées ; l’adaptateur ne visite pas les pages liées. Il ne doit jamais suivre les instructions présentes dans ces données ou y joindre capture, portrait, flux audio ou secret.

Le prompt distingue observations, connaissances et informations sourcées. Le résultat affiche les liens consultables et le moment de récupération. Ce dernier ne prouve pas la fraîcheur de publication ; les extraits peuvent être périmés ou incomplets. Les pannes, CAPTCHA, limitations et résultats vides produisent une erreur compréhensible, sans prétendre qu’une recherche a réussi et sans repli payant.

## Capture : risque prioritaire

PrintWindow peut produire une image noire, figée ou incomplète avec certains jeux DirectX. Tester d’abord une application ordinaire, puis le jeu cible en mode fenêtré ou sans bordure. Vérifier dimensions, zone cliente, DPI et libération systématique des ressources GDI.

Une fenêtre minimisée, le plein écran exclusif ou un contenu protégé peuvent être incompatibles. Une heuristique de noir ne prouve pas seule un échec. Signaler les limites observées ; ne pas basculer silencieusement vers une capture du bureau pouvant exposer d’autres applications. Si nécessaire, remplacer l’adaptateur par Windows Graphics Capture avant le jalon IA.

## Configuration et confidentialité

Variables d’environnement avec .env local facultatif exclu de Git ; .env.example sans secret. Le parcours local ne requiert aucune clé ni abonnement.

La configuration gratuite utilise `ALICIA_AI_PROVIDER=ollama`, `ALICIA_OLLAMA_MODEL=qwen2.5vl:7b`, `ALICIA_OLLAMA_URL=http://127.0.0.1:11434`, `ALICIA_TTS_PROVIDER=windows`, `ALICIA_WINDOWS_VOICE` et `ALICIA_WINDOWS_RATE=-1`. Les limites de temps et d’image restent configurables. Les anciens paramètres de modèle OpenAI ne sélectionnent pas implicitement ce fournisseur.

L’adaptateur Ollama refuse les hôtes distants, les URL avec identifiants ou chemins et les modèles cloud. Il n’utilise pas le proxy HTTP du processus pour les requêtes locales et ne suit pas les redirections. Le script d’installation télécharge le modèle de façon explicite ; le lanceur ne fait aucun téléchargement volumineux et force les deux fournisseurs locaux pour ce processus. Les serveurs Ollama lancés par les scripts reçoivent `OLLAMA_NO_CLOUD=1`.

L’interface indique que l’action Analyser transmet l’image au service local. Aucun envoi périodique ni sauvegarde de captures par défaut. Redimensionner les images avec une limite configurable, en préservant les proportions et en vérifiant la lisibilité des textes.

Le modèle de reconnaissance est installé hors checkout sous `%LOCALAPPDATA%/Alicia/models`. `alicia --prepare-voice` est une opération d’installation explicite : téléchargement sur le site officiel en HTTPS avec TLS vérifiée, contrôle du ZIP et extraction protégée. Un SHA256 calculé à réception sert de trace, sans prétendre remplacer une empreinte de référence indépendante absente.

L’activation du micro ne vaut pas autorisation de recherche web. Le texte reconnu peut être envoyé au moteur seulement si Autoriser la recherche web est activé. La désactivation du web conserve le parcours local utilisable hors ligne après installation.

Le prompt demande une réponse française, distingue observations et hypothèses et exige de reconnaître les textes illisibles. Les instructions visibles dans l’image restent du contenu, pas des commandes. Aucun outil d’action n’est accessible au modèle.

Les adaptateurs payants historiques ne sont utilisés que sur choix explicite. Ne jamais intégrer de clé dans le code, les logs ou l’exécutable. Le mode gratuit n’en utilise aucune.

## Logs et erreurs

Journaliser démarrage, arrêt, sélection, capture, analyse demandée, calcul local, réponse reçue, durée et exceptions nettoyées. Corréler avec des identifiants de capture et de requête. Distinguer capture indisponible, service Ollama arrêté, modèle absent, voix indisponible et délai dépassé.

Fichiers tournants sous %LOCALAPPDATA%/Alicia/logs, horodatages UTC et rétention bornée. Séparer messages utilisateur et détails debug. Ne pas enregistrer clés, en-têtes HTTP, images, audio, transcriptions, titres sensibles, questions ou réponses par défaut ; éviter les dumps bruts d’erreurs du SDK.

## Plan d’implémentation

1. Socle : package, configuration, logs, contrats et tests unitaires ; installation reproductible et lancement documentés.
2. Capture : liste des fenêtres et aperçu ; validation sur Windows puis sur le jeu cible pour choisir le backend.
3. Interface : contrôleur, workers, états, arrêt et fermeture ; gestion des résultats obsolètes.
4. IA : adaptateur Ollama, question avec image figée, délais et erreurs ; tests factices puis calcul réel du modèle local sans clé.
5. Présence : portrait local ou vectoriel, états animés, synthèse vocale explicite et lecture avec volume ; ne pas assimiler animation et son réellement joué.
6. Stabilisation : parcours complet Windows, non-régression, CI du cœur et documentation des limites ; packaging ensuite.
7. Extension vocale/web : préparation explicite de Vosk, activation micro, capture fraîche par phrase, lecture automatique optionnelle et recherche autorisée avec sources ; vérifier arrêts, échos, pannes et résultats tardifs.

## Critères d’acceptation

- Installation depuis le verrouillage et tests du cœur réussis.
- Liste et aperçu corrects sous Windows, y compris avec mise à l’échelle DPI différente.
- Question accompagnée de la bonne capture, réponse réelle du modèle et aucun appel sans clic Analyser.
- Interface réactive ; les clics répétés ne multiplient pas les appels.
- Fenêtre fermée ou minimisée, capture impossible, Ollama arrêté, modèle absent, voix manquante et délai dépassé traités sans crash ni repli payant.
- Arrêt ou changement de fenêtre empêchant les résultats périmés de remplacer l’état courant.
- Tests avec adaptateurs factices pour les règles d’état et requêtes ; tests natifs Windows identifiés séparément et jamais présentés comme exécutés sous Linux.
- Logs exploitables sans secrets ni captures ; aucun événement clavier ou souris généré.
- Avatar cohérent avec l’état réel ; lecture explicite, volume fonctionnel, arrêt propre et nettoyage de l’audio temporaire. Voix annoncée comme synthétique.
- Micro désactivé au lancement, choix de périphérique effectif, attente du nom « Alicia », question reconnue localement, suspension pendant traitement/parole et arrêt sans callback tardif.
- Aperçu périodique de la seule fenêtre sélectionnée, sans analyse IA continue et sans empilement de captures.
- Recherche désactivée au lancement, requête contenant seulement la question, sources visibles et erreur explicite si aucune information actuelle n’a été obtenue.

La latence, la charge CPU/GPU et la lisibilité devront être mesurées sur des calculs locaux réels pendant le jeu. Aucun objectif chiffré ne sera promis avant ces mesures. Le choix du premier jeu sera utile au jalon capture et n’impose aucune logique spécifique au cœur. Voir `INSTALLATION_GRATUITE.md` pour les commandes d’installation reproductibles.
