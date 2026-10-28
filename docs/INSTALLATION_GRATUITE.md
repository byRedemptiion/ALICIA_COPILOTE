# Alicia — Installation locale gratuite sous Windows

Le parcours par défaut utilise Ollama (`qwen2.5vl:7b`), faster-whisper français et Kokoro, voix française féminine `ff_siwis`. Aucun abonnement, crédit API ou compte OpenAI n’est requis. Les téléchargements initiaux nécessitent Internet ; l’analyse locale et les voix sont utilisables hors ligne ensuite. La recherche web autorisée nécessite toujours Internet.

## Installation ou mise à jour

Extraire la nouvelle archive, puis double-cliquer sur **Installer_Alicia.bat**. Attendre le message de fin avant de fermer la fenêtre. Le script conserve le `.env` existant et ne demande aucune clé API.

L’installation prépare :

- uv et Ollama via leurs paquets winget habituels s’ils manquent ; Python 3.12 via uv si nécessaire.
- Les dépendances Python depuis le verrouillage.
- Le modèle visuel local `qwen2.5vl:7b`, plusieurs Go une première fois.
- Les modèles audio par la commande explicite `uv run --frozen alicia --prepare-audio` : Kokoro et ses voix, puis le modèle français de reconnaissance Whisper small.

Kokoro utilise les fichiers de la publication officielle `model-files-v1.1` du projet [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx). Les ressources audio représentent plusieurs centaines de Mo supplémentaires. Whisper utilise le modèle [Systran/faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small), environ un demi-Go selon les fichiers publiés. Les tailles sont indicatives ; les résultats du script font foi.

Les modèles se trouvent normalement sous `%LOCALAPPDATA%/Alicia/models/kokoro` et `%LOCALAPPDATA%/Alicia/models/faster-whisper-small`. Le lancement et les questions ne doivent télécharger aucun modèle. Les fichiers officiels sont récupérés avec TLS vérifié ; aucun checksum ou signature indépendante non vérifié ne doit être inventé. Une installation échouée doit être corrigée avant de déclarer les fonctions audio prêtes.

Le même installateur peut être relancé pour compléter une préparation interrompue. L’ancien modèle Vosk ou les voix SAPI peuvent rester présents ; ils ne sont plus les moteurs par défaut. Les retirer manuellement n’est pas nécessaire.

Depuis PowerShell, les commandes correspondantes sont :

```powershell
.\scripts\setup_local.ps1
.\scripts\start_alicia.ps1
```

Si la politique d’exécution refuse le script local, les fichiers `.bat` le lancent avec une autorisation limitée au processus PowerShell. Ils ne changent pas la politique globale et ne désactivent ni TLS, ni les vérifications des paquets. Si winget manque, mettre à jour **App Installer** depuis Microsoft Store. Une politique d’entreprise reste à gérer avec son administrateur.

## Démarrer et arrêter

Double-cliquer sur **Lancer_Alicia.bat**. Le script démarre Ollama s’il est nécessaire, vérifie le modèle visuel et force les fournisseurs gratuits `ollama`, `kokoro` et `whisper` pour ce processus. Il restaure ensuite les variables de la console ; le `.env` n’est pas réécrit.

Au lancement normal, Alicia commence avec **l’écran principal et le microphone**, sans sélection de fenêtre ni bouton d’activation initial. L’état d’écoute doit être visible. Passez dans votre jeu ou votre navigateur, puis dites « Alicia » suivi de la question. Le contenu affiché sur l’écran principal est celui qu’elle peut analyser ; minimisez son interface pour laisser apparaître le jeu.

**Stop** coupe l’observation et l’écoute et efface le contexte court. **Reprendre** les relance. La sélection d’une fenêtre précise reste une option avancée. Une application masquée n’est pas visible dans une capture du moniteur.

Le mode `Lancer_Alicia.bat` fonctionne avec les réglages gratuits recommandés, même si un ancien `.env` désignait une voix Windows ou un autre fournisseur. Pour une configuration avancée, lancer directement `uv run --frozen alicia` après avoir préparé les modèles correspondants.

La démonstration est disponible via `scripts/start_alicia.ps1 -Demo` ou `uv run --frozen alicia --demo`. Elle n’ouvre pas automatiquement le micro et utilise une image synthétique identifiée.

## Reconnaissance et voix

La reconnaissance Whisper small remplace Vosk par défaut. Elle traite les phrases en français localement après un silence et peut mieux reconnaître les tournures naturelles ; elle ne garantit pas des noms propres ou termes de jeu parfaits. Vérifier le texte reconnu affiché dans Alicia.

Kokoro remplace la voix Windows robotique par une voix neuronale française féminine. Elle reste synthétique et distincte des voix de ChatGPT. Le volume est réglable ; le rendu exact dépend de l’audio et doit être écouté sur votre PC. Une mémoire courte de session aide le suivi, sans modifier les mots réellement reconnus.

L’écoute se suspend pendant le traitement d’une question et la réponse orale pour éviter l’écho, puis reprend après un court délai. L’interruption vocale pendant qu’Alicia parle n’est pas encore proposée. Un problème audio donne un message explicite ; aucun appel payant n’est utilisé en secours.

## Internet et confidentialité

La recherche web reste désactivée par défaut. Après autorisation, seule la question est envoyée au moteur. Les extraits et liens sont affichés avec leur date de récupération ; ils ne constituent pas des pages intégrales vérifiées ni une garantie d’actualité.

L’écran principal inclut les applications visibles. Les captures, l’audio du micro et le contexte court restent locaux ; ils ne sont pas enregistrés dans les logs par défaut. Stop efface le contexte de session. Aucun compte ChatGPT ni session de navigateur n’est utilisé par Alicia.

## Diagnostic

- **Modèle audio absent** : relancer Installer_Alicia.bat ou `uv run --frozen alicia --prepare-audio`.
- **Reconnaissance approximative** : vérifier le micro choisi et le texte reconnu, réduire le bruit du jeu et poser une question moins ambiguë. Le contexte ne remplace pas une bonne transcription.
- **Micro indisponible** : autoriser les applications de bureau dans les paramètres Windows et vérifier qu’un autre programme ne bloque pas le périphérique. Lire l’état puis utiliser Reprendre après correction.
- **Écran incorrect** : vérifier quel écran est principal dans Windows ; afficher le jeu dessus ou choisir une source avancée.
- **Première réponse lente** : laisser les modèles se charger puis mesurer leur latence avec le jeu ouvert. Ne pas promettre une réponse instantanée.
- **Voix indisponible** : vérifier les fichiers Kokoro ; aucune voix Windows ou API payante ne remplace silencieusement le moteur demandé.
- **Recherche refusée** : lire l’erreur ; CAPTCHA et restrictions réseau ne sont pas contournés.

Les tests avec doubles et le smoke test n’exécutent pas les périphériques ou modèles réels. La capture principale, la transcription, le rendu Kokoro et la fluidité du jeu doivent être validés sur Windows selon [la procédure dédiée](VALIDATION_WINDOWS.md).
