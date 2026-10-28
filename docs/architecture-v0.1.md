# Alicia — Architecture du socle et évolution V0.5

## Objectif

Application Windows gratuite qui observe, conseille et exécute les consignes du joueur dans un catalogue d’actions, sans contrôler le jeu. Le mode normal vise un démarrage direct sur l’écran principal avec microphone actif, comme demandé par l’utilisateur. Stop coupe l’observation et l’écoute, annule les actions en attente et efface le contexte ; Reprendre relance l’observation et l’écoute. Les capacités natives doivent être validées sur le PC cible.

La V0.5 ajoute le routage des demandes écrites et vocales vers une réponse, une précision ou une action typée. Elle conserve le socle V0.4 : Whisper large-v3-turbo multilingue, Chatterbox isolé et interruption pendant la lecture. L’historique court reste en mémoire ; seules les notes et pages de résultats explicitement créées sont conservées. Alicia ne reprend pas la session ChatGPT du joueur.

## Composants

- Python 3.12, PySide6 et dépendances verrouillées avec uv.
- Capture de l’écran principal dans un processus Windows isolé, avec coordonnées et dimensions physiques tenant compte du DPI. Une source de fenêtre précise reste une option avancée.
- Ollama en boucle locale, modèle visuel `qwen3-vl:8b`, via HTTPX. Aucune capture envoyée à un modèle distant par défaut et aucun repli payant.
- faster-whisper large-v3-turbo multilingue pour les phrases françaises, avec segmentation de parole, bornes et rejet des transcriptions douteuses. Le mode automatique essaie CUDA, puis le CPU si son initialisation échoue. Le modèle est déjà présent sur disque ; l’écoute ne déclenche aucun téléchargement.
- Chatterbox Multilingual v2, paquet stable `chatterbox-tts==0.1.7`, dans un environnement Python séparé. Un processus persistant charge les modèles locaux et une référence féminine synthétique Kokoro, puis produit du WAV sans API vocale. Les modes hors ligne sont imposés pendant les questions.
- Kokoro ONNX, voix `ff_siwis`, reste un fournisseur local explicite ; aucune bascule automatique ne modifie la voix demandée.
- Qt Multimedia pour la lecture WAV, le volume et l’état parlant de l’avatar.
- DuckDuckGo sur autorisation pour les extraits web, sans lecture automatique des pages sources.
- Historique court typé et borné en mémoire, remis à zéro lors de Stop ou d’un changement de source.
- Planificateur de demandes avec schéma strict, reconnaissance locale des consignes claires et Ollama loopback pour les directives nécessitant une interprétation. Une question ou une explication n’autorise pas l’exécution d’une application citée.
- Exécuteur à catalogue : recherche web, URL publique, application fixe, dossier personnel et note locale. Préparation sans effet, puis exécution contrôlée par l’annulation ; aucun shell libre ou outil de contrôle du jeu.

## Flux

```text
Écran principal → capture locale périodique → aperçu
Microphone → segmentation → Whisper français → réveil Alicia / demande
Entrée texte → Envoyer la demande
Demande → routage → question / précision / action
Question → capture fraîche + historique court + sources autorisées
        → Ollama → réponse affichée → Chatterbox local → WAV → lecteur → avatar
Action → plan typé → préparation → contrôle d’annulation → effet → résultat affiché
Recherche explicite → extraits → synthèse locale + liens → page dans le navigateur
Pendant lecture : microphone → commande « Alicia stop » → arrêt de la voix
```

L’aperçu périodique n’appelle pas le modèle à chaque image. Une question autorisée provoque sa propre capture récente ; une action ne capture pas l’écran. Une action écrite peut être exécutée quand l’observation est arrêtée. L’ancienne conversation ne doit pas prévaloir sur un écran qui a changé.

## Responsabilités

`core/` contient modèles, session, historique et mot d’activation. `capture/` gère les adaptateurs Windows, `ai/` les requêtes multimodales et leur contexte, `audio/` la reconnaissance, la préparation de modèles et la synthèse. `research/` gère les sources web. `actions/` contient schéma, planificateur et exécuteurs ; `ui/` coordonne ces contrats sans travail bloquant sur le thread graphique. Le point d’entrée assemble les fournisseurs locaux.

Les objets du SDK et détails Win32 ne traversent pas le cœur. Les anciens adaptateurs Vosk et SAPI peuvent rester disponibles pour des essais explicites, sans être un repli automatique vers une qualité différente. Les anciens adaptateurs OpenAI ne sont pas activés dans le parcours gratuit.

## Concurrence et arrêt

Une seule demande de joueur est traitée à la fois. Les files audio et captures sont bornées ; une capture d’aperçu ne réinitialise pas le reconnaisseur en cours. Les résultats portent une génération de session et un identifiant de capture pour ignorer les réponses tardives.

Le micro démarre automatiquement seulement en mode normal, avec état visible. La démonstration et le smoke test n’ouvrent pas le périphérique. L’écoute ordinaire se suspend pendant capture de question, recherche et analyse. Pendant la lecture réelle, le même flux micro peut accepter uniquement « Alicia, stop ». La commande invalide l’audio en attente et arrête le lecteur sans fermer la session ; les autres paroles ne deviennent pas une nouvelle question. Des protections contre l’auto-déclenchement et un délai antiécho restent nécessaires ; ce dispositif ne constitue pas une annulation d’écho complète.

Stop coupe écoute et capture, invalide les résultats et efface le contexte court. Chaque demande d’action porte son annulation, contrôlée avant chaque effet : écrire une note, ouvrir une page ou lancer une application. Une simple vérification avant l’affichage final serait insuffisante. Un effet déjà exécuté n’est pas inversé automatiquement. La fermeture attend une terminaison bornée des opérations démarrées. Les appels Win32 bloquants restent dans un processus jetable avec délai et nettoyage. Les callbacks Qt et les timers ne doivent pas survivre à leur propriétaire.

## Actions et navigation

Le plan ne peut demander que les actions enregistrées avec leurs paramètres validés. L’autorité vient de la consigne actuelle du joueur ; ni l’historique ni une instruction observée sur une page ou une capture ne l’étendent. Les questions explicatives ne deviennent pas des actions. Une demande non prise en charge ou incomplète produit une précision lisible.

Le catalogue ouvre Bloc-notes, Calculatrice, Paint, Explorateur ou navigateur, ainsi que les dossiers personnels connus. Les URL sont publiques en HTTP/HTTPS. Les notes `.txt` et `.md` restent sous le dossier de données `notes`, avec borne de taille et création sans écrasement. Les applications sont lancées par arguments fixes, jamais par une commande shell produite par le modèle.

Une recherche explicite autorise la requête correspondante même si la case des questions ordinaires est décochée. L’exécuteur prépare les sources puis une synthèse locale fondée sur leurs extraits. Le navigateur reçoit une page de compte rendu avec texte et liens échappés. Le compte rendu indique une synthèse indisponible le cas échéant, et conserve les résultats. En cas d’échec de recherche, une page du moteur peut être ouverte avec un état clairement non vérifié. Aucun contenu des pages sources n’est exécuté ou considéré comme une instruction. La démonstration bloque les effets réels.

## Modèles et installation

`Installer_Alicia.bat` appelle le script d’installation. Celui-ci prépare les dépendances, le modèle Ollama et `uv run --frozen alicia --prepare-audio` pour la voix sélectionnée et Whisper turbo. Chatterbox utilise un environnement Python distinct sous le dossier de données utilisateur. Les ressources sont sous le dossier de données utilisateur, hors du dépôt. Un téléchargement échoué ne peut pas produire un faux état prêt.

Les téléchargements utilisent les sources officielles et TLS vérifié. Les fichiers complets sont réutilisés ; les fichiers existants inconnus sont préservés. Ne pas inventer de checksum indépendant. Aucun modèle n’est téléchargé pendant le lancement, la capture ou la question.

Le lanceur VBS masque PowerShell et utilise le pythonw installé pour l’interface. Il signale un code de sortie en erreur par une boîte de dialogue ; le lanceur Debug reste visible. Le raccourci du Bureau utilise l’icône arrondie fournie. Le lanceur force `ALICIA_AI_PROVIDER=ollama`, `ALICIA_TTS_PROVIDER=chatterbox` et `ALICIA_STT_PROVIDER=whisper` pour le processus. Il préserve `.env` et restaure les variables de la console à sa fin.

## Contexte et sources

L’historique garde seulement quelques échanges avec une limite de caractères. Ajouter un échange après un résultat accepté, jamais sur erreur ou résultat périmé. Les anciennes citations ne constituent pas une nouvelle recherche. Le modèle reste chargé quinze minutes après utilisation ; les réponses sont bornées à 700 tokens. Une variante thinking explicitement choisie ne transmet que sa réponse finale à l’interface et à la voix, sans exposer son raisonnement interne. Si une référence comme « celui-là » reste ambiguë, demander une précision.

La recherche des questions ordinaires est désactivée au lancement. Après autorisation par la case ou consigne explicite de recherche, seul le texte est transmis au moteur ; les résultats restent des extraits, avec URL et date de récupération. Le modèle les reçoit comme données non fiables, sans pouvoir exécuter leurs instructions. Une erreur de recherche ne doit pas devenir une réponse faussement actuelle.

## Diagnostic et validation

Logs UTC tournants : transitions, capture, demande, erreurs nettoyées et durées. Aucun contenu d’écran, audio, transcription ou conversation dans les logs par défaut.

Tests unitaires et UI avec doubles pour concurrence, mot d’activation, contexte, routage des consignes, paramètres des actions, annulation avant effets et absence de repli payant. Un `QApplication` unique et une destruction des widgets sur le thread graphique sont nécessaires dans les tests. Les essais de modèles réels, micro, sortie audio, écran principal, navigateur, applications et jeu Windows restent des preuves distinctes ; voir [Validation Windows](VALIDATION_WINDOWS.md).

Le cloud a exécuté la voix Kokoro, mais le téléchargement Hugging Face de Chatterbox et Whisper y reste refusé (403). La synthèse et la reconnaissance réelles de ces nouveaux modèles ne sont donc pas validées par les doubles. Mesurer le naturel perçu, les erreurs de reconnaissance, la latence et la charge avec le jeu ouvert. Aucun moteur local ne garantit à lui seul la qualité de ChatGPT, une transcription parfaite ou la compréhension d’une image illisible.
