# Alicia — Installation locale gratuite sous Windows

Le parcours v0.5 conserve Ollama (`qwen3-vl:8b`), Whisper large-v3-turbo multilingue et Chatterbox Multilingual, et ajoute les consignes d’action. Aucun abonnement, crédit API ou compte OpenAI n’est requis. Les téléchargements initiaux nécessitent Internet ; la vision, la reconnaissance, la voix et les actions locales restent ensuite sur le PC. La recherche web autorisée nécessite toujours Internet.

## Installation ou mise à jour

Fermer l’ancienne Alicia, extraire complètement la nouvelle archive, puis double-cliquer sur **Installer_Alicia.bat**. Le terminal reste visible pendant la préparation et les téléchargements, puis se ferme après réussite. Une erreur reste visible ; une préparation échouée ne rend pas les modèles prêts. Le `.env` existant est conservé.

Une installation v0.4 complète peut réutiliser ses modèles locaux : la v0.5 ajoute les actions sans changer les moteurs vocaux ou le modèle visuel.

L’installation prépare :

- uv et Ollama via winget s’ils manquent, puis Python 3.12 et les dépendances verrouillées.
- Le modèle visuel local `qwen3-vl:8b`.
- La voix Chatterbox Multilingual dans un environnement Python séparé, avec une référence féminine synthétique fournie par Alicia.
- Les poids de reconnaissance [faster-whisper-large-v3-turbo](https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo), multilingues et compatibles avec le français.

Prévoir plusieurs Go pour les modèles, le moteur vocal et ses dépendances. Les poids turbo représentent environ 1,6 Go ; la taille totale dépend des paquets installés. Les ressources précédentes sont conservées et ne sont pas automatiquement supprimées. Une bonne carte graphique peut aider, mais la latence avec le jeu ouvert doit être mesurée.

Les données se trouvent normalement sous `%LOCALAPPDATA%/Alicia` : `models/chatterbox`, `models/faster-whisper-large-v3-turbo` et `runtimes/chatterbox`. Chatterbox est isolé pour éviter ses conflits de dépendances avec l’application. Sa référence est un WAV synthétique féminin Kokoro fourni dans les ressources ; aucune voix de personne réelle n’est clonée.

`uv run --frozen alicia --prepare-audio` prépare les modèles de la voix sélectionnée et de Whisper. `uv run --frozen alicia --prepare-expressive-voice` prépare uniquement Chatterbox. Ces commandes d’installation sont explicites ; aucun téléchargement de modèle ne doit se produire au lancement ou pendant une question.

Chatterbox utilise la version stable `chatterbox-tts==0.1.7` du projet [Resemble AI](https://github.com/resemble-ai/chatterbox), avec les fichiers multilingues correspondants. Les téléchargements utilisent les sources officielles avec TLS vérifié. L’intégrité enregistrée localement ne constitue pas une signature indépendante de l’éditeur. Une préparation interrompue peut être relancée ; un dossier existant inconnu est préservé.

L’installateur tente de créer le raccourci **Alicia** sur le Bureau avec l’icône arrondie. Si sa création échoue, `Lancer_Alicia.vbs` reste utilisable directement.

Si winget manque, mettre à jour **App Installer** depuis Microsoft Store. Les scripts `.bat` autorisent leur propre processus PowerShell sans modifier la politique globale. Une politique d’entreprise reste à gérer avec son administrateur.

## Lancer sans terminal

Utiliser le raccourci **Alicia** ou double-cliquer sur **Lancer_Alicia.vbs**. **Lancer_Alicia.bat** appelle le même lancement masqué, mais peut afficher brièvement une console. Les fournisseurs gratuits sont imposés pour ce processus, sans réécrire le `.env`. Ollama est démarré si nécessaire et le modèle est vérifié sans téléchargement caché.

La fenêtre graphique d’Alicia reste visible ; le masquage concerne la console du lanceur et celle d’Ollama. Si le lancement normal ne montre aucune fenêtre alors que le lanceur Debug fonctionne, vérifier que la nouvelle archive a été entièrement extraite et que le raccourci vise ce nouveau dossier.

Une boîte de dialogue signale un échec du lancement masqué. Pour garder la console et diagnostiquer l’installation, utiliser **Lancer_Alicia_Debug.bat**. Les états, erreurs et contrôles restent visibles dans l’interface d’Alicia.

Au lancement normal, **l’écran principal et le microphone sont actifs**. Dire « Alicia » suivi d’une question ou d’une consigne, puis laisser un silence. Pour une question visuelle, passer dans le jeu ou le navigateur sur cet écran et minimiser Alicia pour montrer le contenu. La sélection d’une autre source reste une option avancée.

**Stop** coupe observation et écoute, annule les actions encore en attente et efface le contexte court. **Reprendre** relance observation et écoute. **« Alicia, stop »**, pendant la lecture, coupe seulement la voix et permet une prochaine demande. Les pages déjà ouvertes et les notes déjà créées restent accessibles.

La démonstration reste disponible avec `uv run --frozen alicia --demo` ou `scripts/start_alicia.ps1 -Demo`. Elle utilise une image fictive et n’ouvre pas automatiquement le micro.

## Demander une action

Les mêmes consignes sont utilisables au micro et dans l’entrée texte avec **Envoyer la demande**, sans les transformer en questions. Une action écrite peut être demandée pendant que l’observation est arrêtée :

- « Alicia, cherche un guide de guerrier sur WoW Forever. »
- « Alicia, ouvre la calculatrice. »
- « Alicia, ouvre mes téléchargements. »
- « Alicia, prends une note : acheter des potions. »

La première version sait ouvrir Bloc-notes, Calculatrice, Paint, Explorateur de fichiers ou le navigateur, ouvrir Bureau/Documents/Téléchargements/dossier personnel, ouvrir une URL web publique et créer une note `.txt` ou `.md`. Les notes sont limitées à 10 000 caractères et conservées sous `%LOCALAPPDATA%/Alicia/notes` ; un nom déjà utilisé n’est pas écrasé. Alicia affiche le résultat ou l’information manquante. Une application absente et une action non prise en charge sont signalées.

Une recherche explicite autorise cette requête web même si la case des questions ordinaires reste décochée. Le navigateur affiche une synthèse locale fondée sur les extraits, puis les sources, liens et dates de récupération. Les pages sources ne sont pas lues intégralement. Si la synthèse échoue, le compte rendu affiche les résultats seuls. Si la recherche échoue, le navigateur peut afficher la requête sur le moteur ; Alicia indique alors qu’elle n’a pas obtenu de sources vérifiées.

Les actions n’ont pas besoin d’une capture d’écran. Une question écrite sur l’écran demande une observation active et l’autorisation d’analyse, puis **Envoyer la demande** prend une capture fraîche. **Analyser la capture** garde le parcours manuel. Les résultats vocaux sont lus si la réponse vocale automatique est cochée ; une consigne écrite reste affichée sans lecture imposée. Une demande comme « explique comment ouvrir la calculatrice » doit produire une explication, sans ouvrir l’application. Le catalogue est extensible ; cette version ne donne pas accès à n’importe quelle commande Windows ou aux contrôles du jeu.

## Choisir une voix plus légère

Chatterbox peut être lent sur CPU. Kokoro reste un choix local explicite, sans remplacement automatique de la voix demandée. Depuis PowerShell, à la racine du projet :

```powershell
$env:ALICIA_AI_PROVIDER = "ollama"
$env:ALICIA_TTS_PROVIDER = "kokoro"
$env:ALICIA_STT_PROVIDER = "whisper"
uv run --frozen alicia --prepare-audio
uv run --frozen alicia
```

Le lanceur normal impose Chatterbox ; utiliser le lancement direct ci-dessus pour ce choix avancé. Kokoro utilise `ff_siwis` et les ressources officielles de [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx). L’extrait `examples/voix-francaise.wav` illustre Kokoro, pas Chatterbox.

## Reconnaissance et interruption

Whisper large-v3-turbo remplace le petit modèle précédent. Il traite le français localement après la fin de phrase. Le mode automatique essaie CUDA si son initialisation fonctionne, puis le CPU si nécessaire. Un GPU non compatible ne garantit aucune accélération.

Vérifier le texte affiché : une référence ambiguë et une mauvaise transcription sont deux problèmes différents. Le contexte court aide le suivi d’une question ; il ne corrige pas silencieusement les mots du joueur.

Une demande d’activation ne signifie pas que le micro est déjà prêt. L’interface affiche le chargement du modèle, sa vérification GPU éventuelle, puis l’ouverture du micro. Attendre **En attente de « Alicia » · reconnaissance française locale.** La jauge **Entrée du microphone** indique ensuite le niveau reçu ; elle ne conserve pas le son. Stop puis Reprendre attend la fin d’un éventuel chargement précédent, au lieu de charger plusieurs modèles en parallèle.

L’écoute ordinaire est suspendue pendant le traitement. Pendant la lecture réelle, la détection reste limitée à la commande d’interruption. Dire clairement **« Alicia, stop »**, puis laisser un bref silence. Le délai dépend du micro et de la reconnaissance. Un casque réduit l’écho ; une annulation d’écho complète et l’interruption instantanée ne sont pas garanties.

## Diagnostic

- **L’application ne s’ouvre pas** : lire la boîte de dialogue, puis lancer `Lancer_Alicia_Debug.bat`. Si Debug fonctionne mais pas le raccourci, utiliser les lanceurs de la nouvelle archive : la fenêtre graphique doit rester visible, même sans terminal.
- **Modèle audio absent** : relancer l’installateur ou la commande de préparation correspondante. Aucun service payant ne prend le relais.
- **Reconnaissance incorrecte** : vérifier le micro, réduire le bruit du jeu et comparer les mots affichés avec la phrase dite.
- **Micro indisponible** : autoriser les applications de bureau dans Windows, corriger le périphérique puis utiliser Reprendre.
- **Micro sans réponse et sans erreur** : attendre l’état **En attente de « Alicia »**, puis vérifier la jauge **Entrée du microphone**. Si elle reste immobile quand vous parlez, cliquer Stop, lister les micros, sélectionner l’entrée voulue et Reprendre. Si le niveau bouge, dire clairement « Alicia, ouvre la calculatrice », puis laisser un silence et vérifier le texte reconnu.
- **Chargement prolongé** : le premier démarrage du modèle peut prendre du temps. Lire son état affiché ; des clics Stop/Reprendre répétés ne lancent pas d’autres chargements en parallèle. Le journal distingue la demande d’écoute et le micro réellement prêt, sans enregistrer les paroles.
- **Capturer semblait clignoter** : l’aperçu automatique conserve désormais l’état des boutons. Une demande manuelle envoyée pendant la capture d’aperçu est mise en attente, puis exécutée après celle-ci ; Stop annule cette attente.
- **Écran incorrect** : vérifier quel écran est principal dans Windows, y afficher le jeu ou choisir une autre source.
- **Réponse ou voix lente** : mesurer à chaud avec le jeu ouvert ; vérifier si les moteurs utilisent CPU ou GPU. Kokoro reste disponible explicitement pour une synthèse plus légère.
- **Interruption manquée** : dire la commande complète, utiliser un casque et vérifier le micro ; le bouton Arrêter la voix reste accessible.
- **Recherche refusée** : lire l’erreur. CAPTCHA et restrictions réseau ne sont pas contournés.
- **Application ou dossier introuvable** : utiliser un nom du catalogue et vérifier sa présence sur Windows. Une erreur n’est pas annoncée comme une ouverture réussie.
- **Note indisponible** : vérifier le dossier indiqué et ses droits d’écriture. Les fichiers existants sont préservés.

La recherche des questions ordinaires reste désactivée par défaut. Une consigne explicite de recherche autorise la requête correspondante. Captures, audio et contexte restent locaux dans le parcours gratuit ; les logs ne contiennent pas leur contenu. Les notes et comptes rendus HTML demandés persistent sous `%LOCALAPPDATA%/Alicia/notes` jusqu’à leur suppression manuelle. Les comptes rendus peuvent contenir requête, synthèse et extraits ; Stop efface la conversation en mémoire et conserve ces fichiers.

Les tests cloud utilisent des doubles pour les modèles et périphériques. Les téléchargements Hugging Face y sont bloqués (403) ; suivre [Validation Windows](VALIDATION_WINDOWS.md) pour les essais réels sur le PC cible.
