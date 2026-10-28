# Alicia

Copilote IA gratuit pour Windows : Alicia observe l’écran principal, répond aux questions et conseille sans générer de touches ni de clics. Le lancement normal active l’observation et le microphone, avec un état visible et un bouton Stop.

La v0.4 utilise **Ollama avec Qwen3-VL 8B**, **Whisper large-v3-turbo multilingue** et **Chatterbox Multilingual** pour une voix locale plus expressive. Aucun compte, clé API ou abonnement n’est nécessaire. La qualité et la vitesse restent à évaluer sur votre PC ; Alicia n’est pas cette conversation ChatGPT.

![Interface Alicia](docs/assets/interface-demo.png)

## Installer ou mettre à jour

1. Fermer l’ancienne Alicia et extraire complètement la nouvelle archive.
2. Double-cliquer sur **Installer_Alicia.bat** et attendre la fin des téléchargements. La fenêtre se ferme après réussite ; une erreur reste visible.
3. Utiliser le raccourci **Alicia** du Bureau ou **Lancer_Alicia.vbs** pour un lancement sans terminal.

**Lancer_Alicia.bat** reste compatible et appelle le lancement masqué ; il peut afficher brièvement une console. Une boîte de dialogue signale les erreurs du lanceur masqué. **Lancer_Alicia_Debug.bat** garde une console pour le diagnostic.

L’installateur conserve votre `.env`, prépare les dépendances verrouillées et télécharge explicitement les modèles. Chatterbox dispose d’un environnement Python séparé. Prévoir plusieurs Go pour les modèles et leurs dépendances, et un premier chargement plus lent. Le lancement et les questions ne téléchargent aucun modèle. Voir [Installation gratuite](docs/INSTALLATION_GRATUITE.md), notamment pour choisir explicitement la voix Kokoro plus légère.

## Parler à Alicia

Passez dans votre jeu ou votre navigateur sur l’écran principal, puis dites par exemple :

> « Alicia, décris ce que tu vois. »
>
> « Alicia, lequel de ces objets semble le plus adapté, et pourquoi ? »

Laissez un silence en fin de question. Dire seulement « Alicia » ouvre une fenêtre de huit secondes pour la phrase suivante. Les conversations sans ce mot d’activation ne déclenchent aucune question au modèle. Alicia prend une capture fraîche, utilise le contexte court de la session, affiche sa réponse puis la lit.

**« Alicia, stop »** demande de couper la voix pendant la lecture et de revenir à l’écoute. **Stop**, dans l’interface, coupe l’observation et le microphone et efface le contexte ; **Reprendre** les relance. La détection vocale demande un délai de reconnaissance et doit être testée avec votre micro. Un casque aide à éviter que le son des haut-parleurs revienne dans le micro.

L’écoute ordinaire se suspend pendant le traitement. Pendant la lecture, seules les commandes d’interruption sont prises en compte. Les protections contre l’écho ne constituent pas une annulation d’écho complète.

L’aperçu se met à jour environ chaque seconde, sans analyse IA de chaque image. Alicia voit tout le contenu visible de l’écran principal : minimisez sa fenêtre pour lui montrer le jeu. Une autre source reste accessible dans les options avancées.

## Voix, reconnaissance et réponses

Chatterbox produit du français localement à partir d’une référence féminine synthétique fournie avec l’application. Cette référence vient de Kokoro ; aucune voix de personne réelle n’est clonée. Le rendu Chatterbox doit être écouté sur votre sortie audio avant de le qualifier de plus naturel. Le volume est réglable et l’avatar s’anime pendant la lecture réelle. L’image fournie pour Alicia sert d’icône arrondie et de portrait par défaut.

L’[extrait audio fourni](examples/voix-francaise.wav) est un **exemple Kokoro**, généré réellement lors de la v0.3 ; il ne démontre pas le rendu Chatterbox.

Whisper large-v3-turbo remplace les poids small précédents. Le français reste imposé et les transcriptions peu fiables doivent être rejetées plutôt que transformées en mots inventés. Les noms propres, accents et bruits du jeu restent à tester. La carte graphique est utilisée si l’initialisation CUDA réussit ; le mode automatique peut revenir au CPU, plus lent.

Les réponses privilégient les faits visibles, un conseil court et sa justification utile. L’historique aide les questions de suivi, mais l’écran actuel prime. Si « celui-là » reste ambigu ou qu’un texte est illisible, Alicia doit demander une précision. Le modèle visuel reste chargé quinze minutes après utilisation pour limiter les rechargements ; aucun gain de vitesse mesuré n’est promis.

## Recherche web et données

La case **Autoriser la recherche web** est désactivée par défaut. Après autorisation, seule la question est envoyée au moteur, sans capture ni audio. Les extraits, liens et dates de récupération sont affichés ; les pages complètes ne sont pas lues par ce premier adaptateur. Une date de récupération n’est pas une date de publication.

Les captures, le contexte court et l’audio du micro restent locaux dans le parcours gratuit. Les logs tournants, sous `%LOCALAPPDATA%/Alicia/logs`, ne contiennent ni capture, ni question, ni transcription, ni réponse, ni audio. Stop ou un changement de source efface le contexte. Aucun service payant ne remplace silencieusement un moteur local absent.

## Vérifier le développement

Depuis la racine :

```powershell
uv sync --python 3.12 --frozen --extra dev
uv run --frozen ruff check src tests
uv run --frozen ruff format --check src tests
uv run --frozen pytest -q
uv run --frozen alicia --smoke-test
```

La démonstration `uv run --frozen alicia --demo` utilise une image fictive et ne démarre pas automatiquement le microphone. Le smoke test n’exécute ni périphérique, ni modèle ou recherche réels. Les tests avec doubles ne remplacent pas les essais Windows décrits dans [Validation Windows](docs/VALIDATION_WINDOWS.md).

Vérifications v0.4 : **554 tests Python réussis**, smoke test graphique sans appel IA, construction du paquet avec ses ressources et **10 scénarios/141 assertions PowerShell**. Le moteur CPU Chatterbox a été installé et importé réellement ; son tokenizer français et le watermark fourni ont été vérifiés avec les accès réseau interdits. Ces vérifications ne produisent pas de parole Chatterbox.

La synthèse Kokoro a été exécutée réellement dans le cloud. Les téléchargements Hugging Face de Whisper et Chatterbox y sont refusés par le réseau (403) : leur transcription et synthèse réelles, la capture de l’écran principal, le microphone, l’interruption et le rendu audio Windows restent à valider sur le PC cible.

## Documents

- [Installation gratuite](docs/INSTALLATION_GRATUITE.md).
- [Prompt complet Alicia](docs/PROMPT_PROJET_ALICIA.md).
- [Architecture](docs/architecture-v0.1.md).
- [Feuille de route](docs/ROADMAP.md).
- [Validation Windows](docs/VALIDATION_WINDOWS.md).
