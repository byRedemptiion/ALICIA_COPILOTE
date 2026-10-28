# Alicia — Feuille de route

Chaque jalon doit laisser un parcours cohérent, testé et documenté. Une fonctionnalité codée avec des doubles n’est pas une validation du matériel réel.

## Socle initial

Le projet dispose d’une interface PySide6, de capture Windows, d’un adaptateur IA local Ollama, de logs nettoyés, d’un avatar et d’un parcours texte. Le premier moteur vocal Windows et le premier reconnaisseur Vosk ont montré leurs limites de naturel et de précision lors des essais utilisateur.

## V0.3 — Utilisation directe et audio amélioré

Les demandes actuelles sont :

- Écran principal par défaut, avec actualisation locale périodique et capture fraîche par question.
- Écoute automatique au lancement normal, mot « Alicia », Stop et Reprendre.
- Reconnaissance locale faster-whisper en français.
- Voix neuronale Kokoro française féminine locale, sans service payant.
- Historique court borné en mémoire pour les questions de suivi, effacé par Stop.
- Recherche web sur autorisation avec sources visibles et dates distinguées.

La démonstration et le smoke test restent sans écoute automatique. L’analyse IA ne traite pas chaque image de l’aperçu. Le modèle et la voix ne sont pas cette conversation ChatGPT et ne promettent pas sa qualité exacte. Les vrais essais Windows doivent couvrir écran, bruit, réveil, reconnaissance, écho, latence et fluidité du jeu.

## Fiabiliser l’observation

Comparer les images et détecter les changements pertinents avant d’ajouter des analyses autonomes. Mesurer consommation, taux de captures retenues et lisibilité. Évaluer Windows Graphics Capture si la capture actuelle échoue sur un jeu ; ne contourner aucune protection.

## Conversation et avatar

Mesurer les temps de fin de phrase, transcription, analyse et lecture. Ajouter ensuite sélection de sortie, interruption vocale et contrôle de l’écho suffisamment robuste pour permettre le duplex. L’avatar suit déjà la lecture ; amplitude et phonèmes peuvent améliorer son animation après mesure du coût.

## Contexte approfondi

Étendre le court historique avec observations sourcées, équipement, objectifs et décisions. L’image actuelle prime si l’écran a changé ; un pronom ambigu déclenche une demande de précision. Prévoir provenance et effacement avant une mémoire persistante.

## Conseils spontanés

Ajouter nouveauté, confiance, importance et délai entre interventions. Les modes Silent, Copilot, Coach et Analyst restent à concevoir selon les essais réels. Éviter le bavardage permanent.

## Sources et jeu

Améliorer les requêtes selon le jeu et sa version, comparer les sources et lire des pages complètes si nécessaire. Les extraits actuels ne prouvent pas la fraîcheur d’une mécanique.

## Distribution

Préparer un packaging Windows après validation du socle. Vérifier installation des modèles, mise à jour, licences des ressources, compatibilité du jeu et performances. Un overlay reste facultatif, déplaçable et sans injection dans le jeu.
