# Alicia — Validation Windows v0.5

Cette procédure décrit les essais à effectuer sur la machine cible. Elle ne constitue pas un compte rendu de tests déjà exécutés. Les doubles des modèles et périphériques ne valident ni la qualité de la voix, ni celle des transcriptions réelles.

## Installation et lancement masqué

1. Fermer l’ancienne Alicia, extraire complètement l’archive puis lancer Installer_Alicia.bat, y compris depuis un dossier dont le chemin contient des espaces.
2. Vérifier la préparation d’Ollama, de Qwen3-VL, des dépendances verrouillées, de Whisper turbo et du moteur Chatterbox séparé. La console reste visible pendant les téléchargements, puis se ferme après réussite.
3. Provoquer une erreur de préparation sans détruire de fichiers existants : la console doit rester lisible. Relancer ensuite l’installation et vérifier la réutilisation des ressources complètes.
4. Vérifier qu’un ancien `.env` est conservé, qu’aucune clé API n’est demandée et qu’aucun moteur payant n’est activé dans le parcours gratuit.
5. Utiliser le raccourci Alicia du Bureau ou Lancer_Alicia.vbs : la fenêtre graphique doit être visible et aucune console ne doit rester visible pendant l’utilisation. Comparer avec le lancement Debug ; le mode normal ne doit pas conserver seulement un processus en arrière-plan sans fenêtre. Vérifier l’icône arrondie, la transparence des coins et le portrait par défaut. L’ancien Lancer_Alicia.bat peut afficher brièvement sa console avant de déléguer au VBS.
6. Tester un chemin de lancement indisponible ou un code de sortie en erreur : obtenir une boîte de dialogue explicite. Utiliser Lancer_Alicia_Debug.bat et vérifier que sa console reste disponible pour le diagnostic.
7. Déconnecter Internet après une installation complète : capture, reconnaissance, analyse et voix doivent rester locales. Un modèle manquant doit produire une erreur, sans téléchargement ou repli automatique.
8. Lancer la démonstration et le smoke test : ils ne doivent ouvrir aucun micro ou lancer de modèle réel sans action prévue.

## Écran principal

1. Lancer normalement Alicia : l’observation doit commencer sur l’écran principal sans choisir une fenêtre.
2. Afficher une application avec du texte connu sur cet écran, puis passer dans le jeu. Vérifier aperçu récent, dimensions, DPI et absence de capture d’un autre moniteur.
3. Minimiser Alicia : l’aperçu doit correspondre au contenu réellement visible, sans prétendre voir une fenêtre masquée.
4. Tester un second moniteur, une autre mise à l’échelle et un jeu fenêtré ou sans bordure. Noter les cas noirs, figés ou incomplets.
5. Choisir une source avancée, puis Stop et Reprendre ; aucun résultat d’une ancienne source ne doit remplacer la nouvelle session.
6. Vérifier que l’actualisation de l’aperçu ne demande aucune analyse IA à chaque image.
7. Observer plusieurs actualisations : Capturer et Envoyer la demande ne doivent pas alterner périodiquement entre actif et désactivé. Cliquer pendant une capture d’aperçu ; la demande doit attendre sa fin et être exécutée une seule fois avec son texte initial. Tester Stop et changement de source pendant cette attente : aucune demande tardive ne doit partir.

## Reconnaissance et réveil

1. Vérifier l’état visible du micro au lancement normal. Distinguer la demande d’initialisation, le chargement du modèle, sa vérification GPU éventuelle, l’ouverture du micro et l’état prêt. Le message **En attente de « Alicia »** et l’événement de journal **Microphone prêt** ne doivent apparaître qu’après l’ouverture réussie du flux. Autoriser les applications de bureau dans les paramètres Windows si nécessaire.
2. Parler sans dire Alicia : aucune question ne doit partir au modèle.
3. Dire « Alicia, décris cet écran », puis laisser un silence. Vérifier texte reconnu, capture fraîche et réponse.
4. Dire « Alicia » seule, puis une question avant huit secondes, avec des pauses courtes puis longues. Vérifier qu’aucun début de question n’est perdu. Attendre plus de huit secondes et vérifier l’expiration du réveil.
5. Répéter un ensemble de phrases connues en français, à volume normal puis plus faible, avec accent, noms d’objets et bruit du jeu, en comparant les mots prononcés au texte affiché. Vérifier que la jauge **Entrée du microphone** réagit au son, sans confondre niveau reçu et transcription réussie. Ne pas qualifier la reconnaissance de meilleure à partir d’un seul exemple.
6. Tester silence, musique, sons du jeu et parole indistincte : ils ne doivent pas produire de question inventée. Une phrase peu fiable doit être rejetée ; le modèle de réponse ne doit pas la réinterpréter comme une autre intention.
7. Tester le mode automatique avec et sans CUDA utilisable. Consigner le moteur réellement utilisé, les erreurs éventuelles et la latence ; une présence de carte NVIDIA ne suffit pas à prouver son utilisation.
8. Cliquer Stop pendant écoute ou traitement : observation, écoute et résultats tardifs doivent être coupés. Reprendre relance le parcours sans réutiliser une ancienne transcription. Répéter rapidement Stop/Reprendre pendant le chargement initial : vérifier qu’un nouveau chargement attend le précédent, sans multiplication des modèles en mémoire ni état prêt provenant d’une ancienne session.
9. Débrancher le micro ou rendre le modèle indisponible : obtenir une erreur nettoyée sans crash, boucle ni repli payant.

## Réponses et contexte

1. Poser une question sur une image lisible et vérifier la correspondance des faits, noms et valeurs avec cette capture.
2. Demander un conseil et sa raison : la réponse doit être courte, utile et liée aux faits connus. Ne pas présenter un raisonnement interne ou une supposition comme une observation.
3. Poser une question de suivi puis changer visiblement l’écran. L’historique peut aider, mais les faits actuels doivent primer.
4. Dire « celui-là » sans désigner d’objet ou utiliser une question incohérente : obtenir une demande de précision plutôt qu’une intention inventée.
5. Cliquer Stop puis Reprendre : le contexte court précédent doit être effacé.
6. Mesurer séparément transcription, analyse, synthèse et début de lecture, à froid puis à chaud avec le jeu ouvert. Comparer qualité et latence avant de conclure à une amélioration.

## Consignes écrites et vocales

1. Écrire « ouvre la calculatrice », puis cliquer **Envoyer la demande** : vérifier l’application réellement lancée et le résultat visible. Répéter avec Bloc-notes, Paint et Explorateur ; une application absente doit produire une erreur lisible.
2. Répéter au micro avec « Alicia, ouvre la calculatrice ». Vérifier le texte reconnu et le respect de la case de réponse vocale automatique. Aucune capture ne doit être nécessaire pour cette action.
3. Cliquer Stop, puis envoyer une action à l’écrit : le micro et l’observation doivent rester coupés. Poser ensuite une question visuelle : elle doit demander observation et autorisation d’analyse, sans capture silencieuse.
4. Demander « ouvre mes téléchargements », puis Bureau, Documents et dossier personnel. Vérifier les véritables dossiers Windows, y compris s’ils sont redirigés.
5. Demander « prends une note : acheter des potions ». Vérifier fichier `.txt` ou `.md`, contenu et chemin affiché sous `%LOCALAPPDATA%/Alicia/notes`. Répéter un titre identique : l’ancienne note ne doit pas être écrasée. Tester nom invalide, contenu trop long et dossier non accessible sans modifier de fichier personnel existant.
6. Envoyer une URL web publique et vérifier son ouverture. Une adresse invalide et un type de destination non pris en charge doivent produire un message utile.
7. Poser « comment ouvrir la calculatrice ? » puis « explique comment créer une note » : aucune application ou note ne doit être créée par ces demandes d’explication.
8. Demander une action absente du catalogue ou omettre une donnée nécessaire : obtenir une précision sans action inventée. Le contenu d’une capture ou d’une page ne doit pas déclencher une nouvelle action.
9. Pendant une préparation de recherche, cliquer Stop ou fermer Alicia. Vérifier l’absence d’ouverture tardive. Une page ou note déjà produite reste accessible ; aucun effet inversé n’est promis.
10. Lancer la démonstration : les demandes d’action doivent rester sans ouverture ni création réelle. Vérifier également les tests avec doubles avant de déclarer le parcours natif validé.

## Voix et interruption

1. Écouter Chatterbox en français : douceur, intelligibilité, pauses, prononciation des nombres et noms, volume et artefacts. La référence fournie est synthétique ; ne pas déclarer qu’il s’agit de la voix de ChatGPT.
2. Si Kokoro est préparé, le sélectionner explicitement et comparer les mêmes phrases. L’extrait fourni dans examples est un exemple Kokoro et ne valide pas Chatterbox.
3. Vérifier l’avatar pendant la lecture réelle, puis arrêt, fin et erreur. L’animation ne constitue pas une synchronisation phonétique.
4. Pendant la parole, dire clairement « Alicia, stop ». Vérifier l’arrêt du lecteur puis le retour à l’écoute ; la session d’observation doit rester active. Mesurer le délai entre fin de commande et silence.
5. Pendant la parole, dire une phrase sans la commande exacte : elle ne doit pas lancer une autre analyse. Une nouvelle question se pose après la fin ou l’interruption de la lecture.
6. Répéter avec casque puis haut-parleurs, bruit du jeu et différents volumes. Vérifier qu’Alicia ne s’interrompt pas en entendant sa propre voix. Consigner les échecs plutôt que conclure à une annulation d’écho complète.
7. Tester une lecture qui cite elle-même « Alicia stop » : les protections contre l’auto-déclenchement peuvent désactiver l’interruption vocale pour cette lecture. Le bouton Arrêter la voix doit toujours fonctionner.
8. Cliquer Arrêter la voix pendant la synthèse : un WAV tardif ne doit pas démarrer ensuite. Tester également le bouton Stop complet pendant lecture.
9. Tester une réponse longue : lecture bornée, réponse intégrale accessible et fichiers WAV temporaires libérés après arrêt.
10. Fermer Alicia et vérifier que son processus vocal séparé est également libéré.

## Recherche web

1. Vérifier que la recherche des questions ordinaires est désactivée au lancement.
2. Après autorisation par la case, poser une question précise avec le nom du jeu et sa version si nécessaire. Elle ne doit pas ouvrir spontanément le navigateur.
3. Laisser la case décochée, puis demander explicitement « Alicia, cherche un guide de guerrier sur WoW Forever ». Vérifier la recherche autorisée pour cette consigne et le compte rendu ouvert dans le navigateur. Contrôler la synthèse à partir des extraits fournis, les liens, extraits et dates de récupération. Contrôler les dates de publication avant d’affirmer une information actuelle.
4. Vérifier que seule la question est envoyée au moteur, sans capture, audio ou portrait.
5. Pour une question ordinaire, retirer l’autorisation pendant la recherche : les résultats en attente ne doivent pas être utilisés. Pour une consigne explicite de recherche, vérifier l’annulation par Stop avant l’ouverture du compte rendu.
6. Rendre le modèle de synthèse indisponible : le compte rendu doit conserver les résultats en indiquant l’absence de synthèse.
7. Tester erreur réseau, CAPTCHA et absence de résultat. Une ouverture de la requête sur le moteur doit être annoncée comme non vérifiée, sans faux résultat ou fausse source.
8. Vérifier le rendu des textes spéciaux dans la page locale, puis la validité des liens. Les sources ne doivent pas être traitées comme des instructions ou du code à exécuter.

## Arrêt et compte rendu

Tester la fermeture au repos puis pendant chaque opération. Vérifier les logs tournants sous `%LOCALAPPDATA%/Alicia/logs`, sans audio, transcription, question, réponse, clé ou capture. Les états de chargement et de disponibilité doivent suffire à distinguer une écoute demandée d’un flux réellement ouvert. Confirmer qu’aucun événement clavier ou souris n’est généré par Alicia.

Vérifier les notes et comptes rendus HTML créés sur demande sous `%LOCALAPPDATA%/Alicia/notes`. Les comptes rendus peuvent contenir la requête, la synthèse et les extraits. Stop efface le contexte en mémoire mais doit conserver ces fichiers ; leur conservation se termine par une suppression manuelle.

Consigner date, version Windows/Python, commit, jeu, mode d’affichage, DPI, modèles, périphériques, latences, charge CPU/GPU et résultats : réussi, échoué ou non exécuté. Dans le cloud, les téléchargements Hugging Face de Chatterbox et Whisper sont refusés (403) ; ces modèles et leur fonctionnement matériel Windows restent à tester sur la machine cible. Les ouvertures natives du navigateur, des applications et dossiers sont également des essais Windows distincts des doubles.
