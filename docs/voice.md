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
le [guide Hermes](hermes-setup.md). Astra fonctionne en texte avec la connexion
ChatGPT native de Hermes ; la clé API configurée avait répondu HTTP 401 et
aucun accès effectif aux modèles audio du compte n'est revendiqué. Les trois
modèles sont explicitement configurés.

```sh
python -m promethee.cli --data-dir CHEMIN_SESSION voice --hermes-python CHEMIN_PYTHON_HERMES --hermes-root CHEMIN_HERMES --model MODELE_ASTRA_AUTORISE --api-mode chat_completions --transcription-model gpt-transcribe --speech-model gpt-4o-mini-tts --voice coral
```

`--vault CHEMIN_COFFRE` ouvre la même mémoire que `chat`. Un seul hôte, texte ou
voix, peut posséder la conversation d'un monde. `--base-url` permet un endpoint
explicite différent ; aucun fournisseur de secours n'est choisi.

`--auth hermes-codex --hermes-auth-root RACINE_DONNEES_HERMES` peut sélectionner
la connexion ChatGPT pour le raisonnement. La transcription et la synthèse
exigent toujours `PROMETHEE_OPENAI_API_KEY` et utilisent alors l'API officielle
`https://api.openai.com/v1`. L'accès ChatGPT n'est pas une authentification audio.

- Entrée ouvre le microphone ; une seconde pression termine l'enregistrement.
- Le microphone se ferme automatiquement après dix secondes. Il reste fermé
  avant cette demande, pendant le raisonnement et pendant la parole de l'avatar.
- Une ligne de texte corrige la demande et utilise le même historique.
- `/cancel` coupe enregistrement, réponse ou lecture ; `/quit` ferme l'hôte.
- `/pause` et `/resume` contrôlent l'[initiative configurée](initiative.md),
  avec le même budget que le mode texte. Aucun nouveau tour autonome ne démarre
  pendant l'écoute, la transcription, le raisonnement ou la lecture audio.
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
Chaque réponse vocale possède maintenant un compte rendu de diffusion séparé :
`preparing`, `playing`, `completed`, `interrupted`, `failed` ou `text_only`.
Il conserve le tour, la génération audio, la date et le fait qu'un démarrage
de lecture a été signalé. Il ne contient ni enregistrement ni estimation des
mots entendus : `heard_by_user` et `heard_text` restent inconnus.

Le monde expose les huit comptes rendus les plus récemment mis à jour dans
`recent_speech_deliveries`, avec un indicateur si d'autres sont omis. Astra peut
les consulter via `read_world` avant d'affirmer qu'une réponse a été prononcée.
Une interruption pendant la préparation se distingue d'une interruption après
le démarrage du lecteur. Même `completed` atteste seulement la fin du lecteur,
pas l'audition par l'utilisateur. Le préfixe effectivement diffusé n'est pas
mesuré dans ce diagnostic.

La migration explicite vers le schéma 11 ajoute une valeur inconnue aux anciens
tours, sans inventer leur diffusion. Au redémarrage de l'hôte, les préparations
et lectures restées ouvertes deviennent `interrupted` avec la raison
`host_restarted`. Aucune synthèse ni lecture ne reprend automatiquement.

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

Le compte rendu de diffusion est couvert par les tests de lecture terminée,
arrêt avant/après démarrage, erreur du lecteur, retour tardif, génération
incorrecte, reprise et migration 10 → 11 avec rollback. Les 371 tests passent,
deux sont ignorés ; lint, format et construction réussissent.

`experiments/agent/qualify_speech_context.py` emploie deux appels réels à Astra
avec l'authentification ChatGPT native de Hermes, dans un monde neuf de
qualification. Ses arguments de connexion sont ceux de
`qualify_hermes_codex.py` ; fournir un nouveau `--output` et `--model gpt-6-astra`.
Entre les deux appels, le script enregistre explicitement des événements audio
simulés, puis rouvre l'hôte. Il n'utilise aucun fournisseur audio ni périphérique.

Dans `.local/astra-speech-context-01`, Astra génère la phrase demandée en
14,04 s. Au second appel, il lit `read_world` et explique correctement en
23,40 s que la lecture commencée a été interrompue, sans pouvoir garantir un
seul mot entendu. Aucun audio ni aucune action n'est relancé. Les appels natifs,
réponses, compte rendu et sources du code sont archivés. Cette mesure valide
le raisonnement sur le compte rendu simulé, pas une diffusion acoustique réelle.

## Interfaces vérifiées

La documentation décrit la [transcription de fichiers](https://developers.openai.com/api/docs/guides/speech-to-text)
et la [synthèse PCM à 24 kHz](https://developers.openai.com/api/docs/guides/text-to-speech)
utilisées ici. Les [flux bruts sounddevice](https://python-sounddevice.readthedocs.io/en/0.5.3/api/raw-streams.html)
traitent les buffers sans NumPy.

GPT-Live propose une [délégation client](https://developers.openai.com/api/docs/guides/live-delegation)
pour garder Hermes en backend. L'événement de délégation ne contient pas le
texte de la demande : transcriptions et chronologie doivent être conservées.
Le SDK 2.24.0 installé dans Hermes n'expose pas `live`. Le SDK 3.14.0 a maintenant
été vérifié dans un environnement distinct contre un serveur WebSocket local :
[versions, essais et contrats du transport](live-integration.md). Il n'est pas
encore relié au mode vocal de Promethee et l'environnement Hermes reste inchangé.
Les [corrections Live](https://developers.openai.com/api/docs/guides/live-migration#route-updates-and-corrections)
doivent invalider les anciens résultats avant leur retour au modèle vocal.
