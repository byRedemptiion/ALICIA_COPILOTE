# Alicia — Validation sur Windows

Cette procédure décrit les essais à effectuer sur la machine cible. Elle n’est pas un compte rendu de tests déjà exécutés. Ne pas marquer une étape réussie sans l’avoir observée.

## Préparer

À la racine du dépôt, lancer `scripts/setup_local.ps1`, puis `uv run --frozen pytest`. Le script prépare uv, Python 3.12, Ollama, le modèle visuel local, les dépendances et le modèle français Vosk par `alicia --prepare-voice`. Vérifier sa bonne exécution native : les contrôles PowerShell avec outils factices ne constituent pas une installation réelle Windows. Aucun `.env`, compte distant ou clé API n’est nécessaire.

Vérifier que `qwen2.5vl:7b` apparaît dans `ollama list`, que le modèle Vosk est installé sous `%LOCALAPPDATA%/Alicia/models` et qu’une voix SAPI française féminine est disponible. Les scripts préparent les modèles par défaut ; si un autre modèle est choisi, le télécharger explicitement et l’indiquer dans le rapport. Vérifier le microphone sélectionné et ses autorisations Windows.

Commencer avec une application ordinaire contenant un texte connu, puis avec le jeu choisi en mode fenêtré ou sans bordure. Ne pas utiliser d’informations sensibles pour ces essais.

## Capture et états

1. Lancer `scripts/start_alicia.ps1` ; vérifier que la liste se rafraîchit et qu’Alicia n’y figure pas elle-même.
2. Sélectionner la fenêtre test, démarrer puis capturer. Vérifier titre sélectionné, image récente, zone cliente, dimensions et absence de contenu provenant d’autres fenêtres.
3. Modifier visiblement la fenêtre et recapturer ; l’aperçu doit changer sans appel IA.
4. Tester une autre mise à l’échelle Windows, puis répéter sur le jeu cible. Noter les cas noir, figé ou incomplet ; ne pas les considérer comme une capture valide.
5. Minimiser puis fermer la fenêtre. Vérifier qu’une erreur compréhensible apparaît sans crash ; aucun basculement silencieux vers le bureau ne doit se produire.
6. Arrêter et changer la sélection pendant un traitement. Un résultat ancien ne doit pas remplacer le contenu de la nouvelle session.
7. Avec Vision locale en continu activée, modifier la fenêtre test et observer l’aperçu environ une fois par seconde. Vérifier qu’aucune analyse IA ne démarre pour ces seules images, qu’aucune capture ne s’empile et qu’Arrêter coupe l’actualisation. Désactiver l’option doit conserver la capture manuelle.

## Analyse réelle

1. Sans clé ni compte distant, vérifier que l’interface indique Ollama local. Lancer le script avec un ancien `.env` contenant une sélection OpenAI explicite : le lanceur doit toujours imposer le mode gratuit sans modifier le fichier.
2. Avec Ollama et le modèle déjà installés, capturer un écran lisible, saisir une question puis cliquer une fois sur Analyser. Vérifier que le calcul a lieu sur ce PC.
3. Vérifier que la réponse porte sur l’image affichée, que l’interface reste réactive et que le retour au repos est visible. Vérifier que le choix Réponse vocale automatique correspond au comportement observé ; désactiver ce choix pour une réponse uniquement textuelle.
4. Répéter les clics pendant l’appel : aucune multiplication d’appels ne doit être créée.
5. Arrêter Ollama, sélectionner un modèle local absent et provoquer un délai dépassé : chaque cas donne une explication nettoyée. Aucun appel OpenAI ou autre service payant ne doit être déclenché en secours.
6. Vérifier qu’un texte illisible donne une réponse prudente plutôt qu’une valeur inventée. Évaluer ce point sur plusieurs images ; un cas réussi ne garantit pas toutes les réponses futures.

Après installation complète, désactiver la recherche web, couper l’accès Internet et refaire l’analyse, la transcription et la lecture vocale. Le service de boucle locale doit rester accessible ; ces fonctions locales doivent fonctionner hors ligne. Noter les éventuelles tentatives réseau constatées sans les supposer absentes. Ne pas joindre de capture privée dans le compte rendu.

## Microphone et dialogue

1. Au lancement, vérifier que le microphone est arrêté et qu’aucune permission d’écoute n’est activée silencieusement. Sélectionner un périphérique connu.
2. Essayer Activer le micro sans observation ou sans autorisation d’analyse : un prérequis clair doit empêcher le lancement d’une question non autorisée.
3. Démarrer l’observation, autoriser l’analyse et activer le micro. Vérifier l’état d’attente de « Alicia » et l’indicateur d’écoute.
4. Prononcer une phrase sans le nom : aucune analyse ne doit commencer. Dire « Alicia, que vois-tu ? », puis laisser un silence : une question finale doit apparaître, une capture récente être prise et un seul traitement lancé.
5. Dire seulement « Alicia », puis une question avant huit secondes ; vérifier le déclenchement. Refaire après expiration : la phrase suivante doit être ignorée tant que le nom n’est pas redonné.
6. Avec Réponse vocale automatique activée, vérifier réponse orale et animation ; sans elle, vérifier réponse textuelle sans lecture automatique. Le micro doit être suspendu pendant traitement et lecture et ne pas retranscrire la voix d’Alicia en nouvelle demande.
7. Tester bruit du jeu, silence prolongé, phrase longue et changement de microphone. Distinguer erreur de transcription, question ignorée par le réveil et erreur de périphérique ; ne pas promettre une compréhension parfaite.
8. Couper le micro pendant une phrase, arrêter l’observation pendant une analyse puis fermer l’application. Aucun callback tardif ne doit déclencher capture, calcul ou parole. Après une erreur, vérifier qu’une reprise explicite est nécessaire.
9. Tester modèle Vosk absent et permission micro refusée. L’interface texte doit rester utilisable, sans téléchargement implicite ni repli vers une transcription distante.

## Recherche web et sources

1. Vérifier que la recherche est désactivée au lancement. Une question locale ne doit déclencher aucune requête au moteur.
2. Autoriser la recherche web et demander une information datée sans donnée privée. Vérifier qu’une seule requête bornée contenant le texte de la question est envoyée, sans image, portrait ou audio.
3. Vérifier titres, extraits, URL cliquables et date de récupération affichés. Ouvrir volontairement une source pour contrôler son contenu, sa date et la version du jeu ; ne pas traiter l’extrait comme une lecture complète de la page.
4. Comparer les affirmations de la réponse avec les sources affichées ; signaler toute citation inventée ou confusion entre récupération et publication.
5. Couper Internet, simuler une limite ou un CAPTCHA, puis demander une recherche. Vérifier l’erreur explicite et l’absence d’affirmation selon laquelle une information récente a été trouvée. Aucun service payant ne doit être appelé en secours.
6. Décochez la recherche puis refaire une question vocale : transcription, capture, analyse et voix doivent rester locales. Vérifier qu’une recherche ou réponse ancienne n’écrase pas le résultat après arrêt ou changement de fenêtre.

## Avatar

1. Observer le visuel pendant repos, capture, analyse et erreur : il doit correspondre à l’état réel.
2. Charger une image locale et vérifier son cadrage. Cette image n’est pas la capture envoyée à l’IA.
3. Vérifier que le portrait choisi n’est pas joint à la capture analysée.
4. Après une analyse réussie, cliquer sur Lire la réponse. Vérifier l’annonce de voix synthétique locale, le rendu féminin français souhaité, le réglage du volume et l’animation pendant la lecture effective. Tester l’absence de voix compatible : afficher comment l’installer sans choisir une voix masculine ou anglaise automatiquement.
5. Arrêter la lecture et provoquer une erreur audio : l’avatar doit quitter l’état parlant et le fichier temporaire doit être nettoyé après libération du lecteur. L’animation n’est pas une synchronisation phonétique.
6. Vérifier que redimensionner la fenêtre ou changer le portrait n’interrompt pas la capture et ne déclenche pas de calcul multimodal.

## Journaux et fermeture

Vérifier les événements horodatés sous `%LOCALAPPDATA%/Alicia/logs`, leur rotation et l’absence de clé, image, audio, transcription, question et réponse dans les logs par défaut. Tester la fermeture au repos puis pendant écoute, recherche et analyse ; l’application doit fermer sans attente indéfinie ni résultat appliqué à un écran fermé.

## Rapport minimal

Consigner date, version Windows, commit, versions Python/Ollama/Vosk, noms exacts des modèles, microphone et voix SAPI retenus, jeu et mode d’affichage, mise à l’échelle DPI, backend de capture, résultats observés, latence et charge GPU mesurées, disponibilité du moteur de recherche et étapes non exécutées. Distinguer succès, échec et non testé. Joindre seulement des logs nettoyés et des images explicitement choisies sans données privées.
