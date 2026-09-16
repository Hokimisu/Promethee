# Hermes : cycle de vie, attente et intégration persistante

Audit du 16 septembre 2026, limité aux sources et aux contrats. Aucun appel
modèle, chargement GPU, redémarrage ni modification du harnais dans cet audit.

**Hermes sait conserver un agent, ses clients réseau et ses connexions MCP.
Notre adaptation les recréait à chaque tour.** Ce choix garantit actuellement
qu'un outil du monde reste lié au tour qui l'a produit. Un processus déjà
préparé peut réduire l'attente sans changer ce contrat ; une instance réutilisée
exige de traiter explicitement cette liaison avant d'être une amélioration sûre.

Mise à jour après l'audit : le préchauffage jetable et le contrat vocal système
sont intégrés et testés. Voir les [mesures de qualification](11-short-dialogue.md#préchauffage-hermes-qualifié),
y compris les délais encore longs dans l'essai complet. L'agent résident et
les interfaces vocales natives restent des suites proposées.

## Cinq décisions pratiques

1. **Maintenant :** qualifier le préchargement d'un unique worker jetable,
   avec identifiant réservé inactif, histoire fraîche à l'activation et
   même checkout G: que le harnais. Il conserve la boucle Hermes existante.
2. **Maintenant :** employer le callback natif pour mesurer le premier texte
   visible, séparément de la préparation, du résultat valide et du premier son.
   Ne pas envoyer directement les fragments JSON à la synthèse.
3. **Prochaine optimisation :** comparer l'agent résident avec MCP relancé
   proprement par tour. Ne jamais simuler une nouvelle liaison en changeant
   seulement `task_id` ou le fichier de configuration.
4. **Pour le flux vocal par phrases :** reprendre les interfaces vocales
   natives via un adaptateur vers le worker Vox déjà qualifié ; garder son
   unique thread propriétaire, son profil et son annulation.
5. **Pour une intégration durable plus complète :** évaluer le TUI gateway
   JSON-RPC, déjà responsable des sessions et événements. La migration doit
   définir une seule autorité d'historique et conserver celle du monde ; elle
   ne doit pas être ajoutée comme une deuxième boucle concurrente.

## Versions réellement concernées

| Élément | Observation vérifiée |
| --- | --- |
| Source chargée par le harnais | `G:/Projects/Promethee/.local/hermes-agent`, HEAD `2179a279ae04bfadf8efbc49a01ca0abfb738000`, arbre Git propre lors de la lecture |
| Interpréteur du harnais | `C:/Users/Cat6A/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe` |
| Autre checkout installé | `C:/Users/Cat6A/AppData/Local/hermes/hermes-agent`, HEAD `cd297653fa4fac85f45f7d3ad8e361db0f14e9be`, avec modifications locales |
| Résolution des sources | `.local/realtime-voice-01/serve.py:175–177` passe l'interpréteur C: et `hermes_root` G: ; `hermes_worker.py:119–121` place ce dernier en tête de `sys.path` avant les imports natifs |

L'interpréteur et le checkout ne sont donc pas interchangeables. Les mesures
de construction réalisées directement sur la source C: par un autre essai
ne constituent pas une mesure du harnais G:. Il faut conserver dans les
prochaines mesures `sys.executable`, les `__file__` de `run_agent`,
`agent.conversation_loop` et `tools.mcp_tool`, la révision et l'état modifié.
La résolution ci-dessus a été vérifiée par lecture du lancement et du worker,
sans importer le moteur dans cet audit.

L'origine déclarée du checkout G: est
[`NousResearch/hermes-agent`](https://github.com/NousResearch/hermes-agent).
Le fichier public `agent/interrupt_control.py` à la révision G: a aussi été lu
à distance et comparé au fichier local : égalité après normalisation CRLF/LF,
SHA-256 normalisé
`b5eee15d9f8105afe55c67f918d2f80342cf37acab8683d52afd81beeb23e9de`.
Les liens de code ci-dessous sont figés sur cette révision. La documentation
en ligne est celle consultée le jour de l'audit, susceptible d'évoluer.

## Fonctionnement de référence avant le préchauffage

1. `TextHost.start()` ouvre un tour dans `ConversationStore`. Cette ouverture
   invalide les décisions du précédent tour avant de fermer son processus.
2. `prepare_profile()` crée un profil neuf, avec le serveur MCP
   `promethee.mcp_server --turn-id <id>` et une liste précise d'outils.
3. Le worker lit une seule requête JSON, vérifie que son identifiant correspond
   aux arguments MCP, fixe `HERMES_HOME` et le répertoire courant, résout
   l'authentification puis importe Hermes.
4. `create_agent()` découvre MCP et construit `AIAgent`. Il vérifie les outils,
   le fournisseur, le modèle, le mode API et l'absence de repli silencieux.
5. `run_conversation(message, conversation_history=history, task_id=turn_id)`
   exécute la boucle native. Le worker ferme MCP et renvoie uniquement le
   résultat final ; le processus se termine.

Sources locales : `src/promethee/chat.py:51,94,192,198,354`,
`src/promethee/hermes_worker.py:109,119,148,163,169`,
`src/promethee/hermes_adapter.py:87–126`.

L'attente inclut donc imports, authentification, construction, connexion MCP,
appel(s) modèle puis restitution. Elle ne peut pas être présentée entièrement
comme du raisonnement du modèle. Les mesures déjà produites par le harnais
doivent être conservées avec leur configuration exacte ; cet audit n'ajoute
aucune nouvelle mesure de latence.

## Les mécanismes natifs disponibles

| Besoin | Mécanisme vérifié | Conséquence pour Promethee |
| --- | --- | --- |
| Plusieurs tours sur un agent | `AIAgent.run_conversation(...)` ; le gateway réutilise un agent par clé de session et signature de configuration | La reconstruction par tour n'est pas une exigence de Hermes |
| Clients réseau déjà construits | Cache interne de clients par requête, réutilisé après une fin saine ; client interrompu marqué impropre à la réutilisation | Ne pas créer un second cache HTTP ni fermer le client partagé depuis le thread d'annulation |
| MCP déjà connecté | `discover_mcp_tools()` est idempotent ; découverte en arrière-plan par profil disponible | Dans un même processus et profil stable, la découverte répétée ne doit pas lancer un nouveau serveur |
| Schémas MCP sans connexion immédiate | `lazy: true` et cache de schémas sur disque | Déplace la connexion au premier usage ; ne supprime pas son coût et ne donne pas automatiquement un cache partagé entre nos profils |
| Construction anticipée | Le TUI programme déjà la construction asynchrone d'un agent à la création/reprise de session | Le principe du préchargement est natif ; notre identifiant de tour reste un contrat supplémentaire |
| Texte progressif | Argument `stream_callback` de `run_conversation`, ou `stream_delta_callback` au constructeur | Notre worker pourrait relayer des fragments sans remplacer la boucle Hermes |
| Interruption | `interrupt(...)`, `hard_interrupt(...)`, `clear_interrupt(...)` | Préférer ces signaux natifs dans un worker résident, puis attendre le retour avant de relancer un tour |
| Fermeture | `release_clients()` pour une éviction partielle ; `close()` pour la fin complète | Fermer systématiquement l'agent seulement lorsqu'on termine sa durée de vie, pas après chaque tour résident |

Preuves : [cache d'agents du gateway, lignes 1012–1133](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/gateway/run_turn_runner.py#L1012),
[clients réseau, lignes 339–469](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/client_lifecycle.py#L339),
[découverte MCP, ligne 437](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/tools/mcp_tool_discovery.py#L437),
[construction anticipée TUI, ligne 2564](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/tui_gateway/server.py#L2564),
[fermeture, lignes 908–937](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/run_agent.py#L908).

Le gateway natif ne se limite pas à conserver une référence Python : il
contrôle la signature de configuration, les changements de session et les
écritures externes, actualise certains états par tour, borne son cache et
libère les agents évincés. Copier son dictionnaire de cache sans ces règles
ne reproduirait pas son comportement. Pour une seule conversation Promethee,
une unique instance possédée par un seul thread est une proposition plus
simple qu'une reproduction de ce gateway ; elle reste à qualifier.

## Le point bloquant précis : identité Hermes et autorité du monde

`task_id` est lié au tour interne par `agent/turn_context.py:458–483`. Il ne
réécrit pas la ligne de commande du serveur MCP déjà lancé. Le handler MCP
reçoit `args, **kwargs`, puis appelle
`server.session.call_tool(tool_name, arguments=args)` : aucun identifiant
Hermes n'y est transmis automatiquement comme métadonnée de confiance.
À l'autre extrémité, `WorldTools` conserve le `turn_id` fourni à sa création.
[Handler MCP](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/tools/mcp_tool_handlers.py#L478),
[appel transport](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/tools/mcp_tool_handlers.py#L336),
`src/promethee/mcp_server.py:15,52–62`.

Deux raccourcis seraient incorrects :

- Réécrire `--turn-id` dans le profil puis rappeler `discover_mcp_tools()` ne
  reconfigure pas la connexion déjà présente. Même
  `reconcile_mcp_servers_with_config()` compare les noms activés/supprimés,
  pas les nouveaux arguments d'un serveur de même nom.
- Faire lire « le tour actif » à chaque appel du serveur pourrait donner
  l'autorité du nouveau tour à un appel retardé de l'ancien. L'identité doit
  rester celle capturée au moment de la décision, jamais une valeur globale
  résolue tardivement ni un argument librement choisi par le modèle.

Le cache MCP ne contourne pas cette frontière : son empreinte comprend
`command`, `args`, `url`, transport et filtres d'outils ; le fichier est sous
`HERMES_HOME/cache`. Nos profils neufs et leurs `args` différents produisent
des entrées différentes. Ne pas enlever le tour de l'empreinte pour fabriquer
un gain. [Réconciliation](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/tools/mcp_tool_discovery.py#L480),
[empreinte et stockage du cache](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/tools/mcp_schema_cache.py#L22).

## Streaming : disponible, mais pas encore un flux vocal validé

L'API native applicable est :

```python
result = agent.run_conversation(
    message,
    conversation_history=native_history,
    task_id=runtime_turn_id,
    stream_callback=on_visible_text_delta,
)
```

Le mode `codex_responses` dispose lui aussi d'un chemin streaming natif. Le
callback n'accélère pas la première réponse du fournisseur ; il permet de
recevoir du texte avant la fin lorsque celui-ci arrive progressivement.
Le worker actuel attend toute la réponse et masque cette possibilité.
[Signature native](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/conversation_loop.py#L1573),
[chemin Codex](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/chat_completion_helpers.py#L3364).

Ce flux ne signifie pas « phrase finale déjà validée ». Hermes peut émettre
du texte entre des appels d'outils, des commentaires ou des avis de reprise.
`interim_assistant_callback(text, already_streamed=...)` distingue certains
commentaires et évite leur double restitution. Les callbacks d'affichage et
TTS reçoivent le texte visible nettoyé ; `reasoning_callback` constitue une
surface séparée et ne doit pas alimenter Ariane.
[Livraison des fragments](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/stream_delivery.py#L163).

Notre sortie dirigée est actuellement un objet JSON comprenant paroles et
direction vocale. Lire ses fragments bruts ferait prononcer du JSON ou une
direction incomplète. Première étape recommandée : instrumenter uniquement
le délai du premier fragment visible ; conserver la validation de l'objet
complet avant synthèse. Une future restitution par segments exigera des
segments complets validables, une seule attribution de lecture par segment,
une file bornée et un filtre du tour courant. Ce changement de contrat est
distinct de la simple activation d'un callback.

## Ce que la chaîne vocale native peut remplacer

Hermes fournit déjà `SentenceChunker`, l'interface
`StreamingTTSProvider.stream(text) -> Iterator[bytes]` et un
`StreamingTTSConsumer` pour les plateformes. Un adaptateur déclare son format
audio et implémente `begin_streaming_tts`, `write_streaming_tts`,
`finish_streaming_tts` et `abort_streaming_tts`. La chaîne peut donc réutiliser
ses frontières de phrases et sa livraison, sans réécrire un moteur de
conversation. La documentation distingue le PCM progressif et le repli en
synthèse complète par phrase ; ce dernier ne donne pas le même délai initial.
[Documentation officielle du streaming TTS](https://hermes-agent.nousresearch.com/docs/developer-guide/streaming-tts).

Trois adaptations restent nécessaires pour Ariane :

- Aucun fournisseur VoxCPM n'est présent dans les outils, plugins et registres
  TTS examinés à la révision G:. Le fournisseur doit relayer notre worker Vox
  conservant le profil approuvé ; ne pas activer une sélection automatique
  qui choisirait une autre voix. Déclarer explicitement le format : le contrat
  par défaut du streamer est PCM int16 mono 24 kHz, notre protocole est PCM
  float32 mono 48 kHz. Il faut convenir du format avec le consommateur, pas
  changer seulement l'étiquette de fréquence.
- Le consommateur natif avance le générateur avec
  `await asyncio.to_thread(next, iterator, ...)` : il ne garantit pas que tous
  les `next()` tournent sur le même thread. Il est adapté à un proxy de notre
  protocole, pas à l'insertion directe du générateur CUDA Vox, qui doit rester
  possédé et fermé par son worker. Son arrêt du flux de lecture doit aussi
  envoyer `cancel` au worker ; couper le lecteur ne prouve pas l'arrêt GPU.
- Le découpeur consomme de la prose, pas notre objet JSON paroles/direction.
  Les phrases doivent être validées avant cet étage. Le nettoyeur TTS général
  peut transformer les signes et les unités en mots anglais ; il ne faut pas
  le superposer sans test à notre traitement français des balises Vox.

Preuves : [interface PCM et découpeur](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/tools/tts_streaming.py#L67),
[consommateur et arrêt](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/gateway/streaming_tts_consumer.py#L176),
[normalisation des symboles](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/tools/tts_text_normalize.py#L91).

**Natif utile maintenant :** callbacks et primitives de durée de vie.
**Natif utile après adaptation :** streaming vocal et transport TUI de
sessions. Le mode vocal CLI complet vise le microphone et le lecteur locaux ;
le lancer à côté du harnais ne synchroniserait pas automatiquement son audio,
son historique et les décisions du corps avec Promethee.

## Annulation, historique et profils

`interrupt()` est prévu pour être appelé depuis un autre thread. Il signale
les outils du thread propriétaire, les enfants et certaines requêtes actives.
`hard_interrupt()` ajoute la sémantique d'arrêt explicite, notamment pendant
la compression. L'annulation n'est pas une preuve de retour immédiat de tous
les threads ; le host doit conserver sa limite de temps et son mécanisme de
fermeture du processus si la sortie native n'aboutit pas.
[Contrôle d'interruption](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/interrupt_control.py#L93).

La clôture Promethee doit toujours précéder ce signal. Aucun second
`run_conversation` sur la même instance avant la fin du premier. Le code
natif signale lui-même les départs concurrents susceptibles d'entrelacer les
écritures. Le finaliseur répare les séquences d'outils interrompues et remet
certains états par tour à zéro ; ne pas réimplémenter ces opérations ni
remplacer l'historique natif par les seules paroles affichées.
[Identité et concurrence](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/turn_context.py#L458),
[finalisation](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/turn_finalizer.py#L217).

Un profil stable par processus simplifie l'isolation. Changer `os.environ`
ou `os.chdir()` entre deux threads d'un même worker serait incorrect.
Hermes possède des scopes natifs via `set_hermes_home_override`, scopes de
secrets et `copy_context()` pour son multiplexage ; adopter uniquement la
première fonction ne reproduit pas l'ensemble de cette isolation. Notre
préparation jetable peut conserver un environnement fixe dès le démarrage.
Pour des processus résidents, laisser l'authentification à Hermes, avec ses
règles de rafraîchissement et d'identité du compte ; ne pas partager un token
copié indéfiniment entre profils.
[Multiplexage officiel](https://hermes-agent.nousresearch.com/docs/developer-guide/multiplexing-gateway),
[scopes de profil](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/hermes_constants.py#L25),
[rafraîchissement Codex](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/client_lifecycle.py#L554).

## Choix recommandé et limites

| Option | Gain attendu, à mesurer | Coût et condition |
| --- | --- | --- |
| Un seul worker jetable préparé en avance | Sort imports/construction/MCP du chemin critique lorsqu'il est prêt | Plus petit changement compatible avec la clôture actuelle ; chaque tour consomme son worker, donc aucun partage du pool réseau entre tours |
| Un `AIAgent` résident, serveur MCP recréé par tour | Conserve imports, agent et clients ; paie encore la reconnexion MCP | Étape intermédiaire possible, mais nécessite cycle de fermeture/reconnexion vérifié et profil stable |
| Agent et MCP résidents | Évite davantage de démarrages | Nécessite une identité de tour de confiance par appel ; modification du pont Promethee, pas simple option Hermes |
| TUI gateway natif | Sessions, streaming et annulation déjà exposés | Surface officielle pertinente à long terme ; migration de l'autorité d'historique, des outils et des permissions à concevoir, pas raccourci immédiat |

**Pour l'essai en cours : garder un seul worker anticipé, jetable et borné.**
Il reçoit un identifiant réservé mais inactif. L'ouverture atomique du vrai
tour active exactement cet identifiant et fournit l'historique à jour,
seulement au moment du message. La préparation ne doit produire ni appel
modèle ni décision. En cas de worker absent, périmé ou échoué, retour au
chemin normal ; pas de file illimitée de workers. La fermeture doit retirer
aussi le worker préparé inutilisé et ses processus MCP. Cette proposition
ne revendique aucun gain mesuré par le présent audit.

L'étape résidente intermédiaire peut employer les primitives natives
`shutdown_mcp_servers(scope=..., names={"promethee"})`, nouvelle configuration,
`discover_mcp_tools()` puis `refresh_agent_mcp_tools(...)`, **après retour du
tour précédent** et revalidation de l'ensemble exact des outils. Elle ne
doit pas appeler `agent.close()` entre deux tours ni `reset_session_state()`
à chaque message : ce dernier correspond à une frontière de session. Cette
séquence reste une proposition à tester, pas une intégration livrée.
[Fermeture MCP ciblée](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/tools/mcp_tool_lifecycle.py#L130),
[actualisation des outils](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/tools/mcp_tool_agent.py#L87).

Hermes documente officiellement les trois transports ACP, TUI JSON-RPC et
HTTP/SSE ; pour un hôte personnalisé souhaitant tout le cycle de session,
le TUI expose notamment `prompt.submit`, `session.interrupt`,
`session.history` et les événements de texte/outils. Il n'est pas nécessaire
d'inventer un nouveau protocole Hermes si cette migration devient utile.
Elle ne remplace cependant pas les garanties du runtime du monde.
[Intégration programmatique officielle](https://hermes-agent.nousresearch.com/docs/developer-guide/programmatic-integration).

## Qualification minimale avant de changer de cycle de vie

- Vérifier les sources effectivement importées et comparer à configuration
  identique : premier démarrage, tour préparé, message arrivant avant la fin
  de préparation. Séparer préparation hors requête et délai visible.
- Mesurer temps jusqu'au premier appel fournisseur, premier texte visible,
  objet de parole valide, premier PCM et dernière fin ; le temps d'import
  n'est pas du temps de raisonnement, le premier token n'est pas le premier son.
- Bloquer un ancien appel d'outil, interrompre, ouvrir le tour suivant puis
  libérer l'appel : aucune mutation, parole ou note obsolète ne doit passer.
- Prouver qu'un worker préparé ne peut modifier le monde avant activation ;
  qu'il reçoit l'historique courant, pas une copie capturée pendant sa création.
- Tester annulation pendant MCP/API/streaming, arrêt pendant préparation,
  sortie anormale et expiration de préparation. Vérifier processus enfants,
  un seul propriétaire de conversation, aucune reprise de fragment ancien.
- Pour une instance résidente, tester authentification expirée, changement de
  session/configuration, schémas MCP inchangés et modifiés, puis interruption
  suivie d'un nouveau tour. Vérifier l'historique complet et les outils natifs,
  pas uniquement le texte final visible.

La recherche confirme donc des capacités sous-exploitées, surtout les
callbacks et la durée de vie de l'agent. Elle ne justifie ni la suppression
de la clôture des tours ni l'attribution de toute la latence restante à Hermes.
