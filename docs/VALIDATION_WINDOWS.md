# Alicia — Validation Windows

Cette procédure décrit les essais à effectuer sur la machine cible. Elle ne constitue pas un compte rendu de tests déjà exécutés.

## Installation

1. Extraire la nouvelle archive et lancer Installer_Alicia.bat.
2. Vérifier la préparation d’Ollama, des dépendances verrouillées, de Whisper et de Kokoro. Un message d’erreur ne vaut pas une installation réussie.
3. Relancer l’installation : les ressources complètes doivent être réutilisées sans remplacement de fichiers utilisateur.
4. Vérifier qu’un ancien `.env` est conservé et qu’aucune clé API n’est demandée pour le parcours gratuit.
5. Lancer la démonstration et le smoke test : ils ne doivent ouvrir aucun micro ou lancer de modèle réel sans action prévue.

## Écran principal

1. Lancer normalement Alicia. L’observation doit commencer sur l’écran principal sans sélectionner une fenêtre.
2. Ouvrir une application ordinaire avec du texte connu sur cet écran, puis passer dans le jeu. Vérifier aperçu récent, dimensions, DPI et absence de capture d’un autre moniteur.
3. Minimiser Alicia : l’aperçu doit correspondre au contenu réellement visible sur l’écran principal, sans prétendre voir une fenêtre masquée.
4. Tester un second moniteur, une autre mise à l’échelle et un jeu fenêtré ou sans bordure. Noter explicitement les cas noirs, figés ou incomplets.
5. Tester une source avancée puis Stop et Reprendre ; aucun résultat d’une ancienne source ne doit remplacer la nouvelle session.
6. Vérifier que l’actualisation de l’aperçu ne lance aucune analyse IA à chaque image.

## Écoute et réveil

1. Au lancement normal, vérifier l’état visible du micro et l’absence de bouton initial obligatoire. Autoriser les applications de bureau dans les paramètres Windows si nécessaire.
2. Parler sans dire Alicia : aucune question ne doit partir au modèle.
3. Dire « Alicia, décris cet écran », puis laisser un silence. Vérifier texte reconnu, capture fraîche puis réponse.
4. Dire Alicia seule, puis une question avant huit secondes ; attendre plus de huit secondes et vérifier que l’activation a expiré.
5. Répéter avec bruit du jeu, accents, noms d’objets et plusieurs micros. Noter le texte réellement reconnu et les erreurs sans les masquer.
6. Pendant le traitement et la parole, vérifier la suspension de reconnaissance ; aucun écho ne doit créer une seconde question. Après le délai, l’écoute reprend.
7. Cliquer Stop : l’observation, l’écoute et la prise en compte des résultats tardifs s’arrêtent. Reprendre relance le parcours.
8. Débrancher le micro ou rendre le modèle indisponible : obtenir un message nettoyé sans crash, boucle ou repli payant.

## Réponse, contexte et voix

1. Poser une question sur une image lisible et vérifier que la réponse décrit bien cette capture.
2. Poser une question de suivi, puis changer visiblement l’écran. L’historique peut aider, mais les faits de l’image actuelle doivent primer.
3. Utiliser une référence ambiguë comme « celui-là » sans la désigner : Alicia doit demander une précision si elle ne peut pas la résoudre.
4. Cliquer Stop puis Reprendre : le contexte court de la session précédente doit être effacé.
5. Écouter Kokoro `ff_siwis` en français : vérifier naturel perçu, intelligibilité, volume, silence final et absence d’artefacts. Ne pas déclarer qu’il s’agit de la voix de ChatGPT.
6. Vérifier l’avatar pendant lecture, puis arrêt, fin et erreur. L’animation suit la lecture réelle sans prétendre à une synchronisation phonétique.
7. Tester une réponse longue : la lecture doit rester bornée et la réponse intégrale accessible à l’écran.

## Recherche web

1. Vérifier que la recherche est désactivée au lancement.
2. Après autorisation, poser une question précise avec le nom du jeu et sa version si nécessaire.
3. Vérifier sources cliquables, extraits et date de récupération. Contrôler les dates de publication avant d’affirmer une information actuelle.
4. Vérifier que seule la question est envoyée au moteur, sans capture, audio ou portrait.
5. Retirer l’autorisation pendant la recherche : les résultats en attente ne doivent pas être utilisés.
6. Tester erreur réseau, CAPTCHA et absence de résultat. Ne pas présenter une recherche échouée comme une réponse récente vérifiée.

## Arrêt et diagnostic

Tester la fermeture au repos puis pendant une opération. Vérifier les logs tournants sous `%LOCALAPPDATA%/Alicia/logs`, sans audio, transcription, question, réponse, clé ou capture. Confirmer qu’aucun événement clavier ou souris n’est généré par Alicia.

Consigner date, version Windows/Python, commit, jeu, mode d’affichage, DPI, modèles, périphériques, latences et résultats : réussi, échoué ou non exécuté. Les tests cloud avec doubles ne remplacent pas ces essais matériels.
