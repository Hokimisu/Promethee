# Voix de diagnostic

La commande `voice` raccorde une transcription audio à la même boucle Hermes
que `chat`, puis synthétise sa réponse. Elle conserve monde, outils et historique.
Ce mode à déclenchement manuel prépare T11 ; GPT-Live et l'interruption vocale
automatique restent à intégrer et à qualifier.

## Lancer

Installer les extras `agent` et `voice`. Le paquet de base reste sans dépendance
audio. OpenAI 2.24.0 et sounddevice 0.5.3 sont installés dans Promethee ;
l'environnement Hermes qualifié n'est pas modifié.

```sh
uv sync --locked --extra agent --extra voice
```

Configurer localement `PROMETHEE_OPENAI_API_KEY` et une session existante selon
le [guide Hermes](hermes-setup.md). L'accès Astra configuré répond HTTP 401 ;
aucun accès effectif aux modèles audio du compte n'est revendiqué. Les trois
modèles sont explicitement configurés.

```sh
python -m promethee.cli --data-dir CHEMIN_SESSION voice --hermes-python CHEMIN_PYTHON_HERMES --hermes-root CHEMIN_HERMES --model MODELE_ASTRA_AUTORISE --api-mode chat_completions --transcription-model gpt-transcribe --speech-model gpt-4o-mini-tts --voice coral
```

`--vault CHEMIN_COFFRE` ouvre la même mémoire que `chat`. Un seul hôte, texte ou
voix, peut posséder la conversation d'un monde. `--base-url` permet un endpoint
explicite différent ; aucun fournisseur de secours n'est choisi.

- Entrée ouvre le microphone ; une seconde pression termine l'enregistrement.
- Le microphone se ferme automatiquement après dix secondes. Il reste fermé
  avant cette demande, pendant le raisonnement et pendant la parole de l'avatar.
- Une ligne de texte corrige la demande et utilise le même historique.
- `/cancel` coupe enregistrement, réponse ou lecture ; `/quit` ferme l'hôte.
- Pour interrompre une réponse et parler, appuyer sur Entrée avant de parler.
  La détection automatique de prise de parole n'est pas livrée.

`--input-device` et `--output-device` acceptent les indices PortAudio. Les
périphériques doivent accepter du PCM mono signé 16 bits à 24 kHz. Microphone
absent, débordement et sortie indisponible sont signalés sans inventer de
transcription. Une erreur audio laisse le mode texte du programme utilisable.

## Interruptions et états

L'ouverture du micro ou une correction invalide la génération précédente,
vide la lecture audio et ferme ses processus. L'hôte texte invalide aussi les
outils du tour précédent. Une réponse tardive ne peut déclencher ni nouvelle
synthèse ni lecture. Les corrections en attente passent avant les résultats.

Ces opérations ne demandent pas l'arrêt du corps. Une action déjà acceptée
conserve son état ; son annulation explicite passe par le service d'exécution.
Une demande d'arrêt ne vaut jamais confirmation d'arrêt.

Les sorties JSON distinguent `transcribed`, `answered`, `playback_started`,
`playback_finished`, `failed` et `interrupted`. Elles indiquent monde, tour,
génération et source `chained-voice-diagnostic`. `answered` signifie qu'une
réponse texte a été conservée, pas prononcée. Une fin de lecture ne prouve pas
que l'utilisateur l'a entendue ; `heard_by_user` reste inconnu.

L'historique natif conserve les réponses générées, même si leur audio est coupé.
La restitution détaillée de ce qui a réellement été diffusé dans le contexte
conversationnel reste à compléter pour T11.

## Bornes et mesures

Chaque opération audio tourne dans un processus interruptible, avec un délai
maximal de 30 secondes (`--audio-timeout`). Celui de Hermes reste `--timeout`.
Aucun appel audio n'est relancé automatiquement. Un redémarrage ne reprend ni
enregistrement ni audio précédent.

La réponse texte est conservée intégralement. Au-delà de 2 000 caractères,
elle reste affichée sans synthèse (`text_only`). Une synthèse dépassant 60
secondes est refusée. Ce diagnostic attend toute la synthèse avant de lire
son PCM ; il ne prétend pas offrir la latence d'une voix en continu.

Les enregistrements et PCM transitent en mémoire dans des échanges bornés et
ne sont pas sauvegardés automatiquement. Transcriptions et réponses rejoignent
l'historique privé normal de la session. Les sorties de mesure contenant du
texte utilisateur sont également privées.

`seconds_to_playback` mesure du déclenchement utilisateur au lancement du
lecteur, en incluant l'enregistrement éventuel. `cutoff_seconds` mesure le
traitement de la coupure par l'application. Buffers matériels et perception
humaine demandent une mesure distincte. `billed_cost: null` signifie que le
coût facturé est inconnu, pas nul.

## Qualification

Les tests CPU couvrent les cinq phases, le microphone absent, les buffers
bornés, les refus fournisseur, les délais, les générations obsolètes et la
préservation d'une action corporelle. Le vrai SDK audio est exercé dans des
sous-processus contre un serveur local : upload WAV, transcription, réponse
PCM et refus 401 sans relance.

```sh
python experiments/agent/qualify_hermes_host.py --output .local/essai-voix-neuf --hermes-python CHEMIN_PYTHON_HERMES --hermes-root CHEMIN_HERMES --voice
```

`.local/hermes-voice-qualification-01` a raccordé le vrai Hermes et son outil
de lecture du monde aux deux vrais clients audio, avec fournisseurs et
périphérique simulés. Le circuit a pris 16,748 s jusqu'au lecteur synthétique ;
sa coupure a pris 1,50 ms. La série vérifie aussi correction textuelle (104 ms
pour fermer l'ancien processus), délai, erreur fournisseur et reprise de `chat`.
Son monde est classé `qualification` et exclu de la mémoire. Le coût fournisseur
de cet essai local est nul ; ces mesures ne valident ni les modèles du compte,
ni le microphone, ni les haut-parleurs.

Restent à vérifier : accès effectif, qualité française, coût d'une session
réelle, latence utile, interruption automatique et synchronisation avec des
mouvements réellement exécutés. T11 reste en cours.

## Interfaces vérifiées

La documentation décrit la [transcription de fichiers](https://developers.openai.com/api/docs/guides/speech-to-text)
et la [synthèse PCM à 24 kHz](https://developers.openai.com/api/docs/guides/text-to-speech)
utilisées ici. Les [flux bruts sounddevice](https://python-sounddevice.readthedocs.io/en/0.5.3/api/raw-streams.html)
traitent les buffers sans NumPy.

GPT-Live propose une [délégation client](https://developers.openai.com/api/docs/guides/live-delegation)
pour garder Hermes en backend. L'événement de délégation ne contient pas le
texte de la demande : transcriptions et chronologie doivent être conservées.
Le SDK 2.24.0 installé dans Hermes n'expose pas `live` ; le futur raccord devra
utiliser un client compatible sans modifier implicitement cet environnement.
Les [corrections Live](https://developers.openai.com/api/docs/guides/live-migration#route-updates-and-corrections)
doivent invalider les anciens résultats avant leur retour au modèle vocal.
