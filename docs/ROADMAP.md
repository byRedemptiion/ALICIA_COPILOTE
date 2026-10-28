# Alicia — Feuille de route

Chaque jalon doit laisser un parcours utilisable et testé. Les fonctionnalités futures ne sont pas des capacités déjà livrées.

## V0.1 — Parcours manuel et présence visuelle

Socle préparé : package Python, contrats remplaçables, configuration locale, logs, interface PySide6, adaptateur de capture Windows, adaptateur IA multimodal et tests avec doubles locaux.

Le fonctionnement par défaut est désormais gratuit et local : Ollama avec un modèle visuel, puis synthèse Windows française féminine. Aucun abonnement ou clé requis, aucun repli automatique vers OpenAI. Les scripts préparent le modèle une première fois et lancent ensuite les fournisseurs locaux.

L’utilisateur sélectionne une fenêtre, démarre l’observation, capture, vérifie l’aperçu, pose une question et demande explicitement l’analyse. La démo fournit une capture synthétique sans prétendre observer un jeu. L’avatar peut afficher un portrait local ou un visuel vectoriel et réagir aux états de l’application.

Une première lecture vocale optionnelle est prévue dès ce socle : bouton Lire la réponse, voix SAPI française féminine à débit ralenti, volume et animation liée à la lecture réelle. Sa qualité dépend des voix installées ; la synthèse native et la sortie audio Windows restent à valider sur la machine cible. Un aperçu visuel sans audio ne constitue pas cette validation. Un moteur neuronal local pourra améliorer le naturel plus tard sans abandonner la gratuité.

Passage au jalon suivant : capture correcte sur le premier jeu cible, fenêtre et DPI vérifiés, calcul multimodal local réel réussi sans connexion distante, interface réactive, erreurs compréhensibles et logs sans secrets. Un succès Linux ne valide pas la capture Windows. Les scripts PowerShell doivent aussi être exécutés sur Windows avant de les déclarer validés.

## Extension actuelle — Voix, réveil, aperçu et recherche web

Le micro s’active explicitement et attend « Alicia » : une question dans la même phrase, ou dans les huit secondes qui suivent le nom seul, déclenche une capture fraîche puis l’analyse locale. Les autres phrases sont ignorées. La réponse vocale automatique reste un choix visible. L’écoute est suspendue pendant le traitement et la parole ; Arrêter l’observation coupe le micro. La transcription Vosk, son modèle installé explicitement et les périphériques réels nécessitent une validation Windows.

L’option Vision locale en continu actualise la seule fenêtre choisie environ une fois par seconde, sans calcul IA pour chaque image. Le mode garde une concurrence bornée et peut être désactivé. Cette actualisation locale ne remplace pas la détection de changements et ne promet pas des réponses instantanées.

Une recherche gratuite est proposée après autorisation explicite. Elle envoie seulement la question au moteur et affiche titres, extraits, liens et moment de récupération. Elle n’ouvre pas toutes les pages sources et ne garantit pas leur fraîcheur. CAPTCHA, limitation et indisponibilité sont des erreurs explicites, sans repli payant.

Passage aux étapes suivantes : tester mot de réveil dans le bruit du jeu, absence d’auto-écoute, reprise après erreur, résultats tardifs, captures périodiques et questions successives, puis vérifier une vraie recherche depuis le PC cible. Les tests avec doubles ne valent pas ces essais.

## Observation automatique sobre à approfondir

Ajouter comparaison d’images et détection de changements derrière une interface. Mesurer CPU/GPU et taux de captures retenues pendant un jeu avant d’autoriser des analyses autonomes. Prévoir fréquence, seuil, pause et plafond de calculs. Aucun flux vidéo permanent envoyé au modèle par défaut.

## Voix conversationnelle et avatar enrichi

Étendre la première lecture explicite : sélection de sortie, interruption, faible latence et enchaînement après une question vocale selon une préférence du joueur. L’avatar initial suit l’état réel de lecture ; une animation fondée sur l’amplitude ou les phonèmes pourra l’affiner. Prévoir retour au repos sur arrêt ou erreur. Une animation de bouche ne doit pas laisser croire qu’un son est joué lorsqu’il ne l’est pas.

Commencer par une animation 2D légère : bouche, halo et expression. Les options Live2D, 3D ou synchronisation phonétique ne viennent qu’après mesure du coût et validation de l’audio.

## V0.5 — Contexte de session

Ajouter historique court borné, observations sourcées, équipement, objectifs et décisions. Chaque donnée doit pouvoir être distinguée d’une hypothèse. Prévoir effacement et limites de taille avant la persistance sur disque.

## V0.6 — Interventions utiles

Introduire score d’importance, confiance, nouveauté et délai entre interventions. Modes Silent, Copilot, Coach et Analyst selon le besoin réel. Tester les faux positifs et le risque de bavardage ; le joueur doit pouvoir interrompre ou couper Alicia.

## Connaissances externes à approfondir

Améliorer la recherche existante : choix de sources par jeu, prise en compte des mises à jour et de la version, extraction de pages si elle est utile et encadrée, comparaison des sources et gestion plus fine des dates. Distinguer informations observées, données par le joueur et obtenues sur le web sans coupler le cœur au premier titre.

## V0.8 — Overlay et distribution

Étudier un overlay déplaçable et masquable pour le portrait, les sous-titres et l’état, puis le packaging Windows et la gestion des modèles locaux. Vérifier compatibilité des jeux et performances sans injection ni contournement d’anti-cheat.

## Ordre adaptable

Une incompatibilité de capture doit être résolue avant l’automatisation. Une mauvaise lisibilité des objets doit être traitée avant de promettre des conseils fiables. Le coût, la latence et la charge machine doivent être mesurés à chaque ajout majeur.
