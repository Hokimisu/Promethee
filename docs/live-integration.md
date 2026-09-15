# Raccord GPT-Live — transport qualifié localement

Le 15 septembre 2026, OpenAI Python 3.14.0 et websockets 15.0.1 ont été installés
dans `.local/openai-live-env`, avec Python 3.13.12. L'environnement Promethee et
Hermes conservent OpenAI 2.24.0. Cette vérification prépare T11 ; aucune session
GPT-Live distante, aucun microphone et aucun haut-parleur n'ont été ouverts.

## Reproduire la vérification

Depuis la racine du dépôt, créer un environnement neuf et un dossier de sortie
neuf. Exemple Windows effectivement exécuté :

```sh
uv venv --python 3.13 .local/openai-live-env
uv pip sync --python .local/openai-live-env/Scripts/python.exe --require-hashes experiments/agent/live-requirements.lock
.local/openai-live-env/Scripts/python.exe experiments/agent/qualify_live_sdk.py --output .local/essai-live-sdk-neuf
```

Le verrouillage fixe aussi les dépendances indirectes et leurs empreintes. Il
correspond aux versions de l'environnement essayé sous Windows/Python 3.13.
Le script refuse d'autres versions du SDK et de websockets. Il utilise une clé factice explicite et
des adresses de boucle locale pour tous les appels ; aucune authentification
du compte n'est chargée. Les messages et sources sont enregistrés dans la
sortie. L'essai complet a un délai maximal de 30 secondes.

`.local/live-sdk-qualification-01/report.json` conserve trois cas réussis :

| Cas | Preuve obtenue |
|---|---|
| Échange | Connexion `/v1/live/sessions`, configuration `session.start`, attente de `session.started`, émission de PCM brut, lecture de fragments de transcription et délégation, retour au même ID, accusé corrélé et réception de 960 octets audio |
| Refus | L'événement `error` et son code restent accessibles ; aucune seconde connexion |
| Coupure | La fermeture 1011 remonte comme erreur de transport ; aucune seconde connexion |

Le serveur est un doublon local. Ces résultats prouvent la sérialisation et
la lecture du SDK, pas l'acceptation des paramètres par le service distant,
la justesse des transcriptions ou la restitution audio.

## Contrats à conserver dans le raccord Hermes

Le [guide officiel de délégation](https://developers.openai.com/api/docs/guides/live-delegation)
et les types installés de 3.14.0 concordent sur les points suivants :

- Le modèle figure dans `session.start`, pas dans les paramètres de l'URL.
  Le mode `client` laisse l'application appeler l'hôte Hermes existant.
- `session.delegation.created` donne un ID opaque et un horodatage. Il ne
  fournit ni requête utilisateur ni arguments d'outils.
- Les fragments `session.input_transcript.delta` et
  `session.output_transcript.delta` portent texte et intervalles temporels.
  Il n'existe pas d'événement de transcription terminée dans ce contrat.
  Une délégation peut arriver entre deux fragments d'une même phrase.
- Le résultat revient par `session.commentary.append`, avec l'ID reçu intact
  et un texte borné à 500 tokens. L'accusé `session.commentary.appended` se
  corrèle par `client_event_id` ; il ne prouve aucune parole entendue.
- Le PCM du WebSocket principal est brut, mono, signé 16 bits, à la fréquence
  configurée. Les blocs de sortie se lisent dans leur ordre d'arrivée ; leur
  forme diffère des reflets audio horodatés du canal latéral.

Le futur adaptateur doit donc conserver la chronologie, distinguer la demande
connue des fragments incomplets, réserver chaque délégation une seule fois et
invalider les décisions dépassées avant soumission d'une action. Une reconnexion
ne doit pas rejouer silencieusement les travaux. Les comptes rendus de lecture
restent distincts des résultats du cerveau et des résultats corporels.

## Processus de transport

`src/promethee/live_worker.py` s'exécute avec l'environnement séparé ci-dessus.
Il ne charge ni Hermes ni le contrôleur et n'ouvre aucun périphérique audio :

```sh
.local/openai-live-env/Scripts/python.exe -X utf8 src/promethee/live_worker.py --model gpt-live-1 --voice marin --max-seconds 120
```

L'accès distant utilise uniquement `PROMETHEE_OPENAI_API_KEY`, vers l'endpoint
officiel. L'entrée et la sortie sont des événements JSON, un par ligne. Le parent
attend `session.started`, draine continuellement la sortie et cadence le PCM à
24 kHz. Chaque bloc d'entrée doit contenir au plus une seconde de PCM16 mono.
La file d'entrée contient au plus huit événements ; une ligne dépassant
1 Mio ou une commande invalide déclenche la fermeture. Les append de contexte
acceptent au plus 4 000 octets UTF-8 ; le parent doit aussi respecter les
500 tokens du service, cette limite en octets n'étant pas un comptage de tokens.

La fin de l'entrée, `session.close` ou la durée maximale déclenche une fermeture
explicite. Le processus attend jusqu'à 15 secondes le bilan `session.closed` :
une durée d'usage finie et non négative ainsi qu'une fermeture normale sont
nécessaires pour sortir avec succès. Une erreur, un bilan absent ou une coupure
sort avec le code 1 ; une clé absente avec le code 2. Les messages d'erreur du
fournisseur ne sont pas recopiés, car ils peuvent contenir des données privées.
Le parent doit garder une échéance et pouvoir tuer le processus si ses propres
canaux sont bloqués. Il n'y a ni reconnexion ni rejeu automatique.

Qualification du processus réel, avec serveur WebSocket local et clé factice :

```sh
.local/openai-live-env/Scripts/python.exe -X utf8 experiments/agent/qualify_live_worker.py --output .local/essai-live-worker-neuf
```

L'essai `.local/live-worker-qualification-01` a vérifié sous Windows l'échange
PCM et le retour au même ID opaque, la fermeture sur fin d'entrée, le rejet
d'une commande mal formée, la coupure réseau, le bilan sans usage et l'expiration
de l'attente finale. Chacun des cinq cas ouvre une seule connexion. Le mode
`--test-url` refuse toute adresse hors `ws://127.0.0.1:<port>/v1` et emploie
toujours une clé factice, même si une clé de compte existe dans l'environnement.

## Délégation au même hôte Hermes

La session exécutable fournit désormais `session.instructions` et `session.input`
au démarrage. Les consignes courtes de `live_startup.py` suivent le
[guide officiel de prompting Live](https://developers.openai.com/api/docs/guides/live-prompting) :
dialogue en français, interruption de la parole et conditions de délégation,
sans scénario de vie ni procédure métier supplémentaire. Les capacités mémoire
ne sont mentionnées que si le coffre est effectivement configuré.

`ConversationStore.context()` lit le contexte natif existant sans modifier le
monde. La voix reçoit une vue textuelle citée de cet historique, identifiée par
le monde et sa provenance ; les détails d'outils et messages non textuels restent
dans Hermes. Les textes du cerveau ne sont jamais déclarés entendus. Si la vue
dépasse 6 000 octets UTF-8, elle indique explicitement que l'historique n'est pas
fourni à la voix et qu'il faut consulter Hermes. Aucun résumé n'est inventé ;
l'historique du cerveau reste intact. Ces données ne commandent aucune reprise.

Une délégation issue du seul contexte de démarrage ne lance pas Hermes : un
nouveau fragment de transcription utilisateur est requis. Le fichier généré
`startup.json` reste dans le dossier local de l'essai. Le processus SDK vérifie
sa forme et des limites en octets conservatrices avant toute connexion.

L'essai `.local/live-startup-context-02` a cloné un monde de qualification contenant
un échange Astra réel antérieur. Le vrai SDK a transmis les deux messages de
dialogue, sans les détails d'outils, avec `heard_by_user: null`. Une délégation
artificielle au démarrage n'a ajouté aucun tour, même interrompu, ni aucune action.
Le processus s'est fermé normalement en 3,31 s. Le serveur Live était local ;
l'interprétation des consignes et la voix distante restent à qualifier. Reproduction :
`qualify_live_session.py --fixture-mode startup --history-world <base-de-qualification>`,
avec les autres chemins requis par `--help`.

Cette reprise concerne le contexte déjà connu de Hermes. Les fragments Live qui
n'ont jamais été délégués restent dans le journal local de la session ; leur
réintégration après panne reste à implémenter et à vérifier.

`LiveDelegation` dans `src/promethee/live_delegation.py` reçoit les événements
du transport et utilise le `TextHost` existant. L'appelant sérialise `accept`,
`poll` et `close`. Chaque résultat contient un `event` destiné au transport et
le texte complet destiné à l'affichage ; sa présence ne prouve ni envoi ni lecture
audio. Le [lancement sur fichier audio](live-file-session.md) est exécutable ;
les périphériques restent à raccorder.

Le contexte distingue `user_transcript` de `live_output_transcript`, conserve
l'ordre d'arrivée et les horodatages, et indique explicitement que la phrase
n'est pas garantie complète et que les mots entendus sont inconnus. Ces données
sont transmises dans un message balisé de l'hôte, conservé par l'historique natif
Hermes. Le tour porte la provenance `live`. Aucune transcription de sortie ne
devient une instruction utilisateur ni une preuve d'action.

Une fenêtre de regroupement de 200 ms limite les lancements entre fragments ;
elle ne prouve pas une fin de phrase. Après lancement, un nouveau fragment
utilisateur invalide le tour avant fermeture du processus. Le raccord retourne
alors un avis d'interruption au même ID opaque et ne relance pas ce travail.
Une nouvelle délégation est nécessaire. Une nouvelle délégation concurrente
remplace aussi l'ancienne. Cette règle peut interrompre une demande dont la
transcription arrive tard ; sa fluidité reste à mesurer avec GPT-Live réel.

Le budget de session est explicite, entre 1 et 100 appels Hermes. Les doublons
d'ID sont ignorés, les IDs réutilisés avec un événement différent sont refusés,
et une erreur ferme le contexte en invalidant les outils. Les limites de contexte
échouent explicitement sans tronquer l'historique. Un résultat de plus de
500 octets UTF-8 reste disponible intégralement en texte ; la voix reçoit un
avis de dépassement, jamais une affirmation tronquée. Cette borne conservatrice
est volontairement plus restrictive que les 500 tokens du service.

L'essai `.local/astra-live-delegation-01` a utilisé deux vrais appels à
`gpt-6-astra` via l'authentification native ChatGPT de Hermes. Les événements
Live étaient simulés, sans service vocal ni périphérique :

| Cas | Observation |
|---|---|
| Demande divisée par une délégation | Monde relu, zéro objet rapporté ; réponse en 20,10 s, ID opaque conservé |
| Sortie vocale affirmant une création inexistante | Monde et registre relus ; Astra refuse de confirmer la balle, en 19,95 s |

Deux tours seulement sont enregistrés malgré les retransmissions de délégation,
avec zéro exécution. Les tests CPU couvrent aussi l'arrivée tardive d'une
correction, l'invalidation avant nettoyage, le budget, le résultat trop long et
la perte du transport. L'essai se reproduit avec
`experiments/agent/qualify_live_delegation.py --help` et les chemins Hermes
documentés dans le [guide de configuration](hermes-setup.md).

La [session sur fichier](live-file-session.md) relie le transport à la délégation.
Le raccord explicite `--microphone` et la coupure des buffers locaux sont
couverts avec des périphériques simulés. Restent à implémenter et vérifier :
la coupure acoustique sans reprise de parole obsolète. Les fragments non délégués
sont désormais persistés dans le contexte Hermes, sans relancer une demande au
redémarrage ; les tests vérifient leur provenance et leurs doublons.
Restent à qualifier avec le compte : accès effectif,
conversation française, latence, coût, périphériques et mouvements réels.
La [chaîne de diagnostic](voice.md) reste disponible séparément.
