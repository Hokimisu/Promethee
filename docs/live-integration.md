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
uv pip install --python .local/openai-live-env/Scripts/python.exe openai==3.14.0 websockets==15.0.1
.local/openai-live-env/Scripts/python.exe experiments/agent/qualify_live_sdk.py --output .local/essai-live-sdk-neuf
```

Le script refuse d'autres versions. Il utilise une clé factice explicite et
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

Restent à implémenter et vérifier : ce raccord au même hôte Hermes, le transport
audio continu avec coupure des buffers, la gestion des corrections et la reprise
de contexte. Restent ensuite à qualifier avec le compte : accès effectif,
conversation française, latence, coût, périphériques et mouvements réels.
La [voix de diagnostic](voice.md) reste le seul mode vocal exécutable de Promethee.
