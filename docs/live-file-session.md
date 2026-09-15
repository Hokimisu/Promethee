# Session GPT-Live bornée

`python -m promethee.live_session` relie le processus SDK, le même hôte Hermes,
un fichier WAV entrant et un fichier PCM sortant. Le mode fichier n'ouvre ni
microphone ni haut-parleur ; `--microphone` sélectionne explicitement les
périphériques. Il requiert une session du monde existante et les
[environnements indépendants](live-integration.md) de Promethee, Hermes et du SDK Live.

## Lancer

Depuis l'environnement Promethee, avec les chemins Hermes locaux :

```sh
python -m promethee.live_session --data-dir .local/ma-session --live-python .local/openai-live-env/Scripts/python.exe --live-model gpt-live-1 --live-voice marin --duration 60 --call-budget 1 --input-wav .local/entree.wav --output .local/essai-audio-neuf --hermes-python C:/Users/Cat6A/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe --hermes-root C:/Users/Cat6A/AppData/Local/hermes/hermes-agent --hermes-auth-root C:/Users/Cat6A/AppData/Local/hermes --auth hermes-codex --api-mode codex_responses --model gpt-6-astra
```

L'entrée doit être un WAV PCM16 mono non compressé à 24 kHz, plus court que
la durée choisie. Après le fichier, le processus envoie du silence jusqu'à
l'échéance, pour laisser la voix répondre. Le compte doit disposer de
`PROMETHEE_OPENAI_API_KEY` pour GPT-Live ; l'authentification ChatGPT de Hermes
ne fournit pas cet accès. Le budget compte les appels Hermes, pas le coût audio.

Le dossier de sortie doit être neuf. Il conserve `events.jsonl`, avec provenance
Live/Hermes et identifiants corrélés, `output.pcm` en PCM16 mono à 24 kHz, et
`report.json` avec échantillons et bilan d'usage. `startup.json` conserve les
consignes de voix et la vue historique transmise au démarrage, issue du même
contexte Hermes. Les fichiers restent locaux,
peuvent contenir la conversation et ne sont pas des souvenirs personnels.
Un bilan manquant reste inconnu, jamais assimilé à zéro coût. En cas d'erreur,
les processus sont arrêtés et le rapport indique l'échec ; la finalisation
distante peut alors rester non confirmée. Aucun rejeu ni reconnexion automatiques.

`input_samples` compte les échantillons mis en file vers le processus, pas une
confirmation de leur réception par le service. Un résultat Hermes porte
`delivery: queued` lorsqu'il est mis en file, ou `not_sent_transport_closed`
si l'entrée s'est fermée pendant le calcul. Aucun de ces états ne prouve des
mots entendus. Les sorties du processus sont également consignées avec leur code.

L'envoi de blocs de 480 échantillons tourne indépendamment des démarrages et
arrêts de Hermes. Les files de communication sont bornées ; une saturation
échoue explicitement. Le processus enfant et ses lecteurs/rédacteurs sont
arrêtables même si une entrée reste bloquée. Les corrections reçues sont traitées
avant de demander un résultat à Hermes. Ce chemin enregistre l'audio reçu ;
il ne valide pas l'interruption acoustique ou une voix entendue.

## Périphériques explicites

Remplacer `--input-wav .local/entree.wav` par `--microphone` dans la commande
ci-dessus. L'environnement Promethee doit contenir l'extra `voice`, dont
`sounddevice==0.5.3`. Les options `--input-device N` et `--output-device N`
sélectionnent les indices PortAudio ; sans elles, les périphériques par défaut
sont utilisés. Ils doivent accepter du PCM16 mono à 24 kHz.

La vérification du format n'ouvre aucun flux. Capture et lecture commencent
après `session.started` et se ferment à l'échéance, à la fermeture distante
ou sur erreur. La capture est bornée à 500 ms et la lecture à une seconde ;
un débordement échoue explicitement. Une transcription entrante non vide vide
la lecture locale avant le nettoyage Hermes. Cette coupure n'annule pas le corps.

`playback_requested` distingue ce mode du fichier. `rendered_samples` compte
les échantillons copiés au périphérique, sans prouver leur audition ;
`playback_verified` reste faux. Le journal indique les buffers vidés.
Les tests utilisent des périphériques simulés : aucun matériel audio réel
n'est qualifié. Le délai de transcription, l'écho et les fragments audio
distants arrivant après une interruption restent à qualifier ; cette version
ne garantit pas encore l'absence de parole obsolète exigée par T11.

## Essai du parcours complet

`experiments/agent/qualify_live_session.py` lance le vrai processus SDK et un
vrai appel Astra, avec un serveur Live local et du PCM silencieux. Il crée un
monde neuf de qualification. Le serveur fournit des transcriptions artificielles :
aucune reconnaissance vocale ni génération audio distante n'est testée.
Les arguments de l'essai sont consultables avec `--help` ; les chemins Hermes
et du SDK sont les mêmes que pour la commande ci-dessus.

L'essai `.local/astra-live-session-02` a terminé en 60,27 s : 2 862 blocs PCM
émis, une délégation revenue au même ID après 19,58 s, 960 octets PCM reçus,
une connexion et zéro exécution corporelle. L'écart maximal entre blocs reçus
est de 49,5 ms. Le bilan final simulé annonce 57,24 s audio ; ce chiffre n'est
pas une mesure de facturation OpenAI. Astra a relu le monde et rapporté l'absence
d'objets et l'état corporel non confirmé.

Le premier essai s'était arrêté sur saturation. Il a révélé que l'attente de
20 ms par message dans le processus SDK ne laissait aucune marge au flux 50 Hz.
Elle est désormais de 5 ms. Les cinq cas de qualification du processus repassent
après cette correction. Les tests CPU couvrent les files bloquées, les lignes
invalides ou trop longues, l'audio pendant un appel bloquant et le bilan final
absent ou associé à une autre session. 399 tests passent, deux sont ignorés.

Les dépendances SDK ont également été réinstallées dans un environnement neuf,
depuis `experiments/agent/live-requirements.lock`, avec vérification des empreintes.
Les cinq cas de transport y passent (`.local/live-worker-locked-01`).

### Fermeture décidée par le serveur

L'option `--fixture-mode expired` du même script provoque une expiration après
le premier bloc entrant. Elle n'effectue aucun appel Astra. L'essai
`.local/live-session-expiry-02` s'est fermé en 3,09 s, avec une connexion,
zéro tour Hermes, zéro action et un processus sorti avec le code 0. Le bilan
simulé annonce 0,02 s ; 3 360 échantillons avaient été mis en file côté client.
Cette différence illustre pourquoi le compteur local ne remplace pas le bilan.

Une erreur d'écriture ne masque plus le bilan final en attente sur la sortie.
L'entrée audio s'arrête, les décisions Hermes sont invalidées et le lecteur
attend une fermeture confirmée. À réception du bilan, les commandes encore
en file sont abandonnées et l'entrée standard du SDK est fermée. Le premier
essai réel de cette variante recevait le bilan mais le processus ne sortait
pas proprement ; la fermeture explicite de cette entrée a corrigé le parcours.

Les tests couvrent aussi une réponse Hermes qui finit pendant cette fermeture :
elle n'est ni envoyée ni rejouée. Un code de sortie non nul, des données mal
formées ou un événement fournisseur après le bilan restent des échecs, même
si un bilan d'usage valide les précède.

T11 reste ouvert : périphériques, interruption du son en lecture, reprise du
contexte vocal, accès au service distant, conversation réelle, latence et coût
restent à qualifier.
