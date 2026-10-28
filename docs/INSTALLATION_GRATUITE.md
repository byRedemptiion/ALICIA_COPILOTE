# Alicia — Installation locale gratuite sous Windows

Le parcours v0.4 utilise Ollama (`qwen3-vl:8b`), Whisper large-v3-turbo multilingue et Chatterbox Multilingual. Aucun abonnement, crédit API ou compte OpenAI n’est requis. Les téléchargements initiaux nécessitent Internet ; la vision, la reconnaissance et la voix restent ensuite locales. La recherche web autorisée nécessite toujours Internet.

## Installation ou mise à jour

Fermer l’ancienne Alicia, extraire complètement la nouvelle archive, puis double-cliquer sur **Installer_Alicia.bat**. Le terminal reste visible pendant la préparation et les téléchargements, puis se ferme après réussite. Une erreur reste visible ; une préparation échouée ne rend pas les modèles prêts. Le `.env` existant est conservé.

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

Une boîte de dialogue signale un échec du lancement masqué. Pour garder la console et diagnostiquer l’installation, utiliser **Lancer_Alicia_Debug.bat**. Les états, erreurs et contrôles restent visibles dans l’interface d’Alicia.

Au lancement normal, **l’écran principal et le microphone sont actifs**. Passer dans le jeu ou le navigateur sur cet écran, puis dire « Alicia » suivi de la question. Minimiser l’interface d’Alicia pour montrer le jeu. La sélection d’une autre source reste une option avancée.

**Stop** coupe observation et écoute et efface le contexte court. **Reprendre** les relance. **« Alicia, stop »**, pendant la lecture, coupe seulement la voix et permet une prochaine demande.

La démonstration reste disponible avec `uv run --frozen alicia --demo` ou `scripts/start_alicia.ps1 -Demo`. Elle utilise une image fictive et n’ouvre pas automatiquement le micro.

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

L’écoute ordinaire est suspendue pendant le traitement. Pendant la lecture réelle, la détection reste limitée à la commande d’interruption. Dire clairement **« Alicia, stop »**, puis laisser un bref silence. Le délai dépend du micro et de la reconnaissance. Un casque réduit l’écho ; une annulation d’écho complète et l’interruption instantanée ne sont pas garanties.

## Diagnostic

- **L’application ne s’ouvre pas** : lire la boîte de dialogue, puis lancer `Lancer_Alicia_Debug.bat`.
- **Modèle audio absent** : relancer l’installateur ou la commande de préparation correspondante. Aucun service payant ne prend le relais.
- **Reconnaissance incorrecte** : vérifier le micro, réduire le bruit du jeu et comparer les mots affichés avec la phrase dite.
- **Micro indisponible** : autoriser les applications de bureau dans Windows, corriger le périphérique puis utiliser Reprendre.
- **Écran incorrect** : vérifier quel écran est principal dans Windows, y afficher le jeu ou choisir une autre source.
- **Réponse ou voix lente** : mesurer à chaud avec le jeu ouvert ; vérifier si les moteurs utilisent CPU ou GPU. Kokoro reste disponible explicitement pour une synthèse plus légère.
- **Interruption manquée** : dire la commande complète, utiliser un casque et vérifier le micro ; le bouton Arrêter la voix reste accessible.
- **Recherche refusée** : lire l’erreur. CAPTCHA et restrictions réseau ne sont pas contournés.

La recherche web reste désactivée par défaut et n’envoie que la question après autorisation. Les captures, audio et contexte restent locaux dans le parcours gratuit ; les logs ne contiennent pas leur contenu.

Les tests cloud utilisent des doubles pour les modèles et périphériques. Les téléchargements Hugging Face y sont bloqués (403) ; suivre [Validation Windows](VALIDATION_WINDOWS.md) pour les essais réels sur le PC cible.
