# Alicia — Feuille de route

Chaque jalon doit laisser un parcours cohérent, testé et documenté. Une fonctionnalité vérifiée avec des doubles ne prouve pas son fonctionnement matériel réel.

## Socle et v0.3

Le projet dispose d’une interface PySide6, de capture Windows, d’Ollama local, d’un avatar, d’un parcours texte, de recherche web sur autorisation et d’un historique court en mémoire. La v0.3 a introduit l’écran principal et le microphone au lancement, Whisper small et la voix Kokoro, après les limites de Vosk et SAPI constatées par l’utilisateur.

## V0.4 — Voix, reconnaissance et lancement

Les demandes de cette version sont :

- Lancement normal sans terminal visible, raccourci avec icône arrondie et console de diagnostic séparée.
- Image fournie par l’utilisateur pour l’icône et le portrait par défaut.
- Chatterbox Multilingual local pour une voix française plus expressive, avec une référence féminine synthétique et un moteur Python isolé.
- Whisper large-v3-turbo multilingue à la place des poids small, français imposé et rejet des transcriptions douteuses.
- Qwen3-VL 8B, réponses courtes liées aux faits visibles, clarification des demandes incohérentes et réutilisation du modèle chargé.
- « Alicia, stop » pendant la lecture pour couper la voix, en conservant la session d’observation et l’écoute suivante.

Le bouton Stop coupe toujours observation et écoute et efface le contexte. La démonstration et le smoke test n’ouvrent pas automatiquement le micro. Aucun téléchargement de modèle ne doit se produire pendant une question et aucun moteur payant ne prend le relais.

La qualité de Chatterbox, la précision de Whisper turbo, la latence d’interruption et les performances avec un jeu restent des critères d’essais réels, pas des résultats déduits du code. Les téléchargements Hugging Face sont refusés par le réseau du cloud ; voir [Validation Windows](VALIDATION_WINDOWS.md).

## V0.5 — Rechercher et ouvrir une page sur commande

Demande utilisateur : « Alicia, trouve-moi le stuff du war sur WoW Forever » doit permettre de lancer une recherche et d’ouvrir dans le navigateur une page utile à la demande, au-delà d’une réponse dans le chat. Cette fonction est prévue pour la prochaine version et n’est pas activée dans la v0.4.

Reconnaître l’intention de recherche et l’ouverture demandée, employer le jeu, le serveur, la spécialisation, le contenu visé et la version lorsqu’ils sont connus, puis demander la précision qui change réellement la recommandation. Ne pas présenter un guide d’une autre version comme applicable au serveur. Vérifier les sources avant d’ouvrir une page ; fournir une synthèse avec les liens lorsque plusieurs guides sont nécessaires. La demande explicite autorise la recherche de cette question, sans transmettre capture ni audio. Une simple question ne doit pas ouvrir spontanément le navigateur.

Ce parcours reste gratuit et doit conserver un contrôle visible sur la navigation. L’ouverture d’une page ne doit pas créer de touches ou de clics dans le jeu.

## Fiabiliser l’observation

Comparer les images et détecter les changements pertinents avant d’ajouter des analyses autonomes. Mesurer consommation, taux de captures retenues et lisibilité. Évaluer Windows Graphics Capture si le backend actuel échoue sur un jeu, sans contourner de protection.

## Conversation et avatar

Mesurer chaque étape du parcours vocal. Améliorer le contrôle de l’écho et le délai d’interruption à partir d’essais casque et haut-parleurs avant de proposer des questions libres pendant la lecture. Ajouter une sélection de sortie et étudier une synthèse par phrases si elle apporte un gain réel sans dégrader l’intonation. L’avatar suit déjà la lecture ; amplitude et phonèmes demandent une validation séparée.

## Contexte approfondi

Étendre l’historique court avec observations sourcées, équipement, objectifs et décisions. L’image actuelle prime si l’écran change ; un pronom ambigu déclenche une précision. Prévoir provenance et effacement avant toute mémoire persistante.

## Conseils spontanés

Ajouter nouveauté, confiance, importance et délai entre interventions. Les modes Silent, Copilot, Coach et Analyst restent à concevoir selon les essais réels. Éviter le bavardage permanent.

## Sources et jeu

Améliorer les requêtes selon le jeu et sa version, comparer les sources et lire des pages complètes si nécessaire. Les extraits actuels ne prouvent pas la fraîcheur d’une mécanique.

## Distribution

Préparer un packaging Windows après validation du socle. Vérifier installation des modèles, mise à jour, licences des ressources, compatibilité et performances. Un overlay reste facultatif, déplaçable et sans injection dans le jeu.
