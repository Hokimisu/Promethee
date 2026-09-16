# Pont Hermes

Le pont local expose cinq outils du monde, plus quatre outils de mémoire lorsque
`--vault` désigne un coffre configuré. Il utilise le même runtime que le contrôleur
cinématique. La commande `chat` lance désormais la boucle native Hermes dans
son environnement séparé, avec historique persistant et interruption des appels.
Le raccord textuel est vérifié avec Astra : conversation, lecture du monde,
historique après redémarrage, posture exécutée et résultat d'annulation retrouvé
après interruption du raisonnement. Les limites motrices de T07 et la voix de
T11 restent ouvertes. L'[initiative](initiative.md) reste désactivée sans configuration
explicite de son budget dans la session.

## Conversation textuelle

Ouvrir d'abord une base `session` avec le contrôleur du [guide moteur](motion-validation.md),
ou créer un monde vide sans corps avec `promethee --data-dir CHEMIN_SESSION init-session`.
Pour ajouter la mémoire, initialiser un coffre neuf selon le [guide mémoire](memory.md),
puis ajouter `--vault CHEMIN_COFFRE` à `chat`. Les anciennes sessions non classées
peuvent converser mais ne sont pas admissibles à cette mémoire.
Une base existante doit être au schéma 11 ; arrêter ses processus avant d'appliquer
la [migration explicite](contracts.md). Installer l'extra `agent` dans le Python
de Promethee. Les premiers essais utilisent Hermes 0.20.5 ; le préchauffage
et le [mode résident](#agent-résident) sont qualifiés sur Hermes 0.21.3,
révision `2179a279ae04bfadf8efbc49a01ca0abfb738000`.
Pour l'API, configurer `PROMETHEE_OPENAI_API_KEY` localement, sans la mettre dans
Git ni dans la commande. Le modèle et le mode d'API sont explicites.

```sh
python -m promethee.cli --data-dir CHEMIN_SESSION chat --hermes-python CHEMIN_PYTHON_HERMES --hermes-root CHEMIN_HERMES --model MODELE_AUTORISE --api-mode chat_completions
```

Cette commande utilise par défaut `https://api.openai.com/v1` ; `--base-url`
permet un endpoint explicitement choisi et `--api-mode codex_responses` sélectionne
l'autre mode accepté par l'adaptateur. Aucun autre fournisseur ni modèle n'est
essayé automatiquement. Une clé absente ou un monde absent échoue avant l'appel.

Une connexion ChatGPT **déjà configurée dans Hermes** peut aussi être utilisée
par sa boucle native, sans clé API ni passage par `codex_app_server` :

```sh
python -m promethee.cli --data-dir CHEMIN_SESSION chat --hermes-python CHEMIN_PYTHON_HERMES --hermes-root CHEMIN_HERMES --model gpt-6-astra --api-mode codex_responses --auth hermes-codex --hermes-auth-root RACINE_DONNEES_HERMES
```

`RACINE_DONNEES_HERMES` désigne la racine existante contenant l'authentification
Hermes, pas son dépôt de code. Le programme crée un profil neuf sous
`RACINE_DONNEES_HERMES/profiles/promethee-IDENTIFIANT_TOUR`. Hermes résout lui-même
l'authentification partagée ; Promethee ne copie pas les fichiers de connexion
dans ces profils. Il n'active aucun profil global, plugin ou outil personnel.
Le modèle, le fournisseur, le mode natif et la liste d'outils sont vérifiés
après construction de l'agent. Un écart provoque un refus.

Ce mode n'accepte que `https://chatgpt.com/backend-api/codex`. Un autre endpoint
est refusé avant la résolution des credentials. Les appels consomment l'accès
ChatGPT existant ; ils ne prouvent pas l'accès à l'API audio. Pour configurer une
connexion manquante, utiliser le parcours d'authentification de Hermes en dehors
de Promethee, puis relancer la commande.

Saisir un message par ligne. Un nouveau message invalide l'appel précédent avant
de fermer son processus, puis démarre le nouvel échange. `/cancel` coupe seulement
la réponse en cours ; `/quit` ferme le chat. Ces opérations n'annulent pas une
action corporelle déjà acceptée. Un arrêt du corps passe par son outil d'annulation.
Les sorties indiquent `completed`, `failed` ou `interrupted` pour **la réponse**,
sans les confondre avec les états d'exécution du corps. Le délai maximal vaut
60 secondes par défaut (`--timeout`). Sans initiative configurée, aucun appel
au modèle n'est fait pendant l'attente d'un message.

Pour un essai de dialogue avec Astra, `--reasoning-effort low` transmet
explicitement le niveau de réflexion à la boucle native Hermes. Sans cette
option, Promethee conserve le réglage par défaut du fournisseur. Ce choix ne
change pas le modèle et ne supprime ni les contrôles des outils ni leurs
confirmations d'exécution.

`--measure-timing` ajoute un objet `timings` aux réponses de l'hôte : résolution
du fournisseur, imports, construction de l'agent, conversation native, fermeture
MCP et durées totales du worker et de l'hôte. Les totaux englobent les étapes et
ne doivent pas être additionnés à celles-ci. Les phases mesurent le temps écoulé,
sans journaliser les accès ni un raisonnement interne. Elles ne séparent pas
lecture du contexte, choix d'émotion et rédaction à l'intérieur d'un appel au
modèle. Les options restent désactivées par défaut et les erreurs peuvent ne
contenir que les mesures disponibles avant l'échec.

`--prewarm` prépare à l'avance un unique processus Hermes et ses outils, sans
appel modèle ni tour actif. Le message réel active ce processus avec
l'historique courant ; la réserve expire après 120 secondes. `/cancel`
conserve la réserve inactive, tandis que la fermeture du chat la détruit.
L'option est désactivée par défaut. Avec les mesures activées, la préparation,
l'attente inactive et l'activation sont distinguées ; le temps total du worker
peut donc inclure une longue attente avant le message.

La qualification sur Hermes **0.21.3**, révision `2179a279…`, et Luna montre
un gain lorsque la réserve est prête, mais pas une fluidité garantie sur des
répliques successives : voir [les mesures complètes](research/11-short-dialogue.md#préchauffage-hermes-qualifié)
et les audits [cycle de vie](research/12-hermes-lifecycle.md) et
[contexte/outils](research/13-hermes-context-tools.md). Le paramètre Python
`system_message` de l'hôte transmet aussi un contrat stable à la boucle native,
hors des messages utilisateur persistés ; il n'active ni SOUL ni mémoire.

Un verrou détenu par le système autorise un seul hôte de conversation par monde.
Le redémarrage ferme les anciens tours, conserve les messages restés sans réponse
et ne réémet aucune action. Sans `--resident`, chaque appel reçoit un profil neuf dans
`conversation-profiles/` en mode API, ou sous la racine Hermes explicitement
choisie en mode ChatGPT, lié au tour et limité aux cinq outils du monde, ou neuf
avec la mémoire. Ces profils
contiennent des données privées ; ils ne sont pas des coffres à importer.
Le contexte natif conservé dans la base fait autorité pour la reprise.

`read_world` ajoute `recent_executions`, contenant les huit résultats les plus
récemment mis à jour et un indicateur `has_more` si d'autres sont omis. Chaque
entrée donne l'identifiant, l'action, le statut, l'éventuelle demande d'arrêt,
les dates, la provenance et l'erreur. Le modèle peut ainsi retrouver l'action
interrompue même si les appels d'outils du tour abandonné ont été écartés de
l'historique. `read_execution` fournit ensuite le détail observé. Le snapshot
et ces résultats sont lus dans la même transaction ; ils ne modifient pas le
schéma du monde et ne constituent jamais une instruction de reprise.

Sous Windows, le processus est créé suspendu, attaché à un groupe dont la fermeture
termine aussi ses descendants, puis démarré. Cela couvre également le lanceur de
l'environnement virtuel et un pont MCP survivant à son parent. Les interfaces
sont celles des [Job Objects](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information)
et de [CREATE_SUSPENDED](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags).
Sous Linux, l'appel possède son propre groupe de processus. Le pilote corporel
indépendant n'appartient pas à ce groupe.

## Agent résident

`--resident` conserve un unique processus Hermes et son `AIAgent` entre les
réponses réussies. L'option est **désactivée par défaut** et implique la
préparation initiale : il n'est pas nécessaire d'ajouter `--prewarm`. Si les
deux options sont présentes, le mode résident est utilisé, sans second worker.
Le mode résident requiert `--auth hermes-codex`, `--api-mode codex_responses`
et une racine d'authentification Hermes existante ; le mode `api-key` est
refusé avant le lancement du processus.

```sh
python -m promethee.cli --data-dir CHEMIN_SESSION chat --hermes-python CHEMIN_PYTHON_HERMES --hermes-root CHEMIN_HERMES_2179 --hermes-auth-root RACINE_DONNEES_HERMES --auth hermes-codex --api-mode codex_responses --model gpt-5.6-luna --reasoning-effort low --resident --measure-timing
```

Le chemin `--hermes-root` choisit les sources importées ; il peut différer
du répertoire contenant `--hermes-python`. L'essai utilise les sources
Hermes 0.21.3 du checkout `2179a279…` avec l'interpréteur d'une installation
séparée. Ce contrôle de provenance évite de comparer deux versions de Hermes.
Le choix de Luna ne modifie pas le modèle par défaut du reste du projet :
`--model` demeure obligatoire et aucun repli automatique n'est ajouté.

La préparation n'appelle pas le modèle et n'ouvre pas de tour actif. À
l'arrivée du message, l'hôte ouvre le tour et charge l'historique courant.
Après une réponse validée, le worker ferme le transport MCP. Pour le tour
suivant, il remplace uniquement l'argument `--turn-id` du même profil dédié,
puis redécouvre les outils et reconstruit leur snapshot natif. Il vérifie les
schémas complets, le modèle, le fournisseur, la session et l'authentification
avant de rappeler `AIAgent.run_conversation`. Aucun identifiant de tour n'est
choisi par le modèle ; conserver l'agent ne conserve pas l'autorité de l'ancien
serveur MCP. Les audits [cycle de vie](research/12-hermes-lifecycle.md) et
[contexte et outils](research/13-hermes-context-tools.md) expliquent ces
contraintes et les interfaces natives retenues.

Les limites temporelles sont distinctes :

- `--timeout` borne chaque tour à **60 secondes par défaut**, à compter de
  l'arrivée du message. Une préparation encore en cours compte donc dans ce
  délai. L'option ne borne pas la durée totale de la conversation.
- La préparation initiale expire après **120 secondes**, démarrage compris.
  Après chaque réponse réussie, le résident dispose de **120 secondes
  d'inactivité** avant fermeture. La CLI n'expose pas de réglage de cette durée.
- `/cancel` au repos conserve le résident. Pendant une réponse, `/cancel`,
  un nouveau message prioritaire ou l'échéance invalident le tour avant de
  détruire le processus et ses descendants. `/quit` ferme aussi le résident
  au repos. Les actions corporelles déjà acceptées conservent leur propre
  cycle d'annulation.

Une réponse échouée, partielle ou interrompue, un historique invalide, un
identifiant réutilisé ou un changement du profil/de l'authentification interdit
la réutilisation. Le prochain tour nécessite une instance neuve ; la requête
échouée n'est pas rejouée automatiquement. Les profils dédiés restent sur
disque et contiennent des données privées. L'historique natif dans SQLite
reste la référence après fermeture ou redémarrage.

Pour un intégrateur Python, `args.resident=True` active le même chemin.
`host.warm_status()` et `host.warm()` peuvent rendre `active` pendant un tour,
puis `ready` après succès ; ils ne créent pas un deuxième agent pendant ce
tour. `host.cancel()` conserve uniquement l'instance au repos, tandis que
`host.close()` ferme toutes les ressources. `worker_wrapper` reste appliqué
à chaque activation ; son `close()` n'est pas appelé après un succès résident,
puisqu'il fermerait le processus conservé. Le paramètre `system_message`
reste fixe pendant sa durée de vie et l'historique est relu à chaque activation.

Avec `--measure-timing`, `mcp_rebind_seconds` mesure la reconnexion et la
validation des outils. `host_total_seconds` mesure le tour courant ;
`worker_total_seconds` est cumulatif pendant la vie du résident. Les phases
`prewarm_seconds`, `import_seconds` et `agent_construct_seconds` ne sont
présentes qu'au premier tour. Ne pas additionner ces phases aux totaux.

### Qualification résident du 16 septembre 2026

Trois tours réels avec Luna, effort `low`, ont utilisé le même `AIAgent` et
le même processus natif, mais trois transports MCP et trois identifiants de
tour distincts. Le monde était neuf, marqué `qualification`, avec cinq outils,
sans mémoire personnelle, GPU, synthèse vocale ni serveur de démonstration.
Le contrat vocal approuvé était transmis via `system_message` ; les trois
réponses JSON ont passé la validation de texte et de direction vocale.

| Mesure | Dialogue 1 | Dialogue 2 | Lecture du monde |
|---|---:|---:|---:|
| Message → résultat hôte | 6,30 s | 6,63 s | 10,41 s |
| Boucle native Hermes | 6,15 s | 4,83 s | 8,39 s |
| Reconnexion et validation MCP | 0,02 s | 1,64 s | 1,86 s |
| Appels modèle rapportés par Hermes | 1 | 1 | 2 |

La préparation initiale a pris **7,78 s**, dont **4,58 s** de construction de
l'agent. Les deux tours suivants n'ont pas reconstruit l'agent. Le troisième
a réellement appelé `read_world` et retrouvé son nouvel identifiant de tour.
Cet essai ne soumet aucune action corporelle ; les tests CPU vérifient
séparément deux soumissions avec un agent déterministe et de vrais processus MCP.

Les preuves locales sont conservées sous
`.local/realtime-voice-01/luna-qualification/run-resident-g-01/` : rapport,
requêtes, résultats et identités natives. Le module effectivement importé
était `G:/Projects/Promethee/.local/hermes-agent/run_agent.py`, SHA-256
`a6839f07a53e27a9d1315bf23fb4876627c06e65a5cd2f6458072ef1af4b6539` ;
les empreintes du raccord testé sont dans `report.json`.

Une batterie CPU tournait pendant cette qualification : ces trois mesures
ne sont pas un comparatif isolé de performances. Elles établissent le réemploi
de l'agent, pas une latence garantie. La reconnexion MCP et les appels modèle
restent dans le délai ; ni streaming du texte ni première parole audible ne
sont mesurés ici. Aucun coût monétaire n'est déduit des compteurs natifs.
Les contrôles de refus des drapeaux natifs `failed`, `partial` et
`completed=False` ont ensuite été renforcés et vérifiés sur CPU, sans nouvel
appel modèle. Les 16 tests dédiés couvrent notamment activation invalide,
réutilisation d'ID, changement de configuration, historique frais, échéance
et destruction des descendants.

## Installation et lancement

Le SDK officiel `mcp==2.0.0` est une dépendance optionnelle, épinglée et verrouillée.
Le paquet de base conserve zéro dépendance d'exécution.

```sh
uv sync --locked --extra agent --extra viewer
uv run --extra agent promethee-mcp --data-dir /chemin/absolu/session
```

La commande parle MCP sur stdin/stdout, pas un protocole conversationnel pour
un terminal humain. La base doit déjà exister, être à jour et porter l'origine
`session`. Aucun monde vide, migration, contrôleur ni mémoire n'est créé par le
serveur. Un fichier SQLite vide est également refusé. Lancer le corps avec
la commande `run` du [guide moteur](motion-validation.md).

Le serveur et le runtime doivent utiliser le même système d'exploitation pour
accéder à SQLite. L'essai décrit ci-dessous utilise Python Windows pour les deux ;
seul le calcul ARDY est dans WSL. Les transactions, le bail du pilote et la
réconciliation restent ceux d'`ExecutionService`. Relancer MCP ne relance ni
l'action ni le modèle moteur. Un corps perdu reste non confirmé jusqu'à sa
réconciliation par le pilote.

## Outils

| Outil | Effet |
|---|---|
| `read_world` | Dernière observation, révision, provenance et état de confirmation |
| `list_capabilities` | Uniquement les actions du contrôleur actif et leurs arguments requis |
| `submit_action` | Soumission de `request_id`, `expected_revision`, `action: {kind,args}` |
| `read_execution` | Statut et observation d'une requête existante |
| `cancel_action` | Demande d'arrêt, sans inventer son accusé |

Un identifiant métier et son enveloppe sont conservés lors d'une retransmission.
Un nouvel identifiant est nécessaire pour une nouvelle intention. `accepted`
et `running` ne signifient pas `completed`. La disponibilité d'une capacité ne
garantit pas qu'une génération passera les contrôles géométriques. Les retours
du pilote, la réconciliation et la commande logique `act` ne sont jamais des
outils MCP. Les textes portés par les objets sont des données.

Avec `--object-interactions` sur le contrôleur, les capacités actives comprennent
aussi création, prise et dépôt cinématiques des modèles `plush` et `ball`. Les descriptions
MCP indiquent les positions XYZ en mètres, Y vertical pour `spawn` et `place` ;
`move` conserve une cible XZ au sol. Les objets libres sont fixes, sans gravité,
et la prise utilise un attachement ponctuel sans fermeture des doigts. Voir les
[limites et essais du contrôleur](spatial-objects.md). L'apparition de ces outils
ne valide pas encore leur utilisation par Astra.

## Configuration Hermes vérifiée

Les premiers essais ci-dessous utilisent l'installation Hermes **0.20.5**, Python
3.11.15, révision `cd297653fa4fac85f45f7d3ad8e361db0f14e9be` incluant un commit
local. Les essais de préchauffage et de résidence utilisent ensuite les sources
Hermes **0.21.3**, révision `2179a279ae04bfadf8efbc49a01ca0abfb738000`, dans un
checkout séparé, sans remplacer l'installation précédente. Les versions ne
doivent pas être confondues lors d'une comparaison de latence.

Les interfaces sont documentées par [Hermes MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp),
les [filtres d'outils](https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference)
et les [profils](https://hermes-agent.nousresearch.com/docs/user-guide/profiles).
Le serveur utilise le [SDK Python officiel](https://github.com/modelcontextprotocol/python-sdk/tree/v2.0.0).

Extrait `config.yaml` du profil de qualification, avec chemins à adapter :

```yaml
mcp_servers:
  promethee:
    command: G:/Projects/Promethee/.venv/Scripts/python.exe
    args:
      - -m
      - promethee.mcp_server
      - --data-dir
      - G:/Projects/Promethee/.local/runtime-mcp-01
    timeout: 10
    tools:
      include: [read_world, list_capabilities, submit_action, read_execution, cancel_action]
      resources: false
      prompts: false
```

Les deux derniers filtres sont nécessaires : Hermes ajoute sinon quatre outils
auxiliaires pour les ressources et prompts annoncés par le SDK. Avec les filtres,
son registre contient exactement les cinq outils préfixés `mcp__promethee__`.

L'essai utilise un `HERMES_HOME` neuf, un répertoire courant séparé du dépôt et un
coffre vide. Il n'a importé ni profil existant, ni souvenirs, ni `AGENTS.md`, ni
scénario. Ce profil sert uniquement au diagnostic : il n'est pas une identité
personnelle de l'avatar. La restriction des outils natifs a été vérifiée à la
construction du véritable agent ; la boucle conversationnelle reste à raccorder.

## Construction de l'agent restreint

`hermes_adapter.py` appelle le vrai constructeur `AIAgent` de la version locale
qualifiée, après `discover_mcp_tools()`. Il utilise uniquement le groupe
`mcp-promethee`, vérifie les cinq noms effectivement transmis à l'agent (neuf
avec un coffre configuré), et
refuse une configuration qui introduirait d'autres outils ou un modèle de secours.
Il ne recrée pas la boucle de raisonnement de Hermes.

Le profil doit aussi contenir :

```yaml
tools:
  tool_search:
    enabled: "off"
```

Sans découverte préalable, le constructeur ne reçoit aucun outil. Avec la
découverte mais sans ce réglage, Hermes remplace les cinq schémas par ses trois
outils de recherche et d'appel différés. Le réglage ci-dessus permet de vérifier
directement la liste exposée. `skip_context_files=True`, `load_soul_identity=False`,
`skip_memory=True` et `skip_background_review=True` empêchent les injections de
contexte, identité et mémoire existantes dans cet adaptateur. La
mémoire Promethee est raccordée explicitement par `--vault`. La boucle est limitée à
huit itérations par appel et aucun repli vers un autre modèle n'est configuré.

Le script [qualify_hermes_scope.py](../experiments/agent/qualify_hermes_scope.py)
construit cet agent sans appeler `run_conversation`. Il requiert le Python de
Hermes, son répertoire d'installation, le Python du pont MCP, un monde `session`
existant et un identifiant de tour ouvert par l'hôte. Exemple de commande :

```sh
HERMES_PYTHON experiments/agent/qualify_hermes_scope.py --output .local/hermes-scope-neuf --hermes-root CHEMIN_HERMES --mcp-python CHEMIN_PYTHON_PROMETHEE --data-dir CHEMIN_SESSION --turn-id IDENTIFIANT_DU_TOUR
```

Remplacer les chemins et l'identifiant ; le dossier de sortie doit être neuf.
L'essai réalisé avec le script est conservé dans `.local/hermes-scope-qualification-02`.
Son rapport confirme les cinq outils, l'exclusion du contexte projet et l'absence
de modèle de secours. Le nom `gpt-6-astra`, la clé factice et le mode
`chat_completions` servent uniquement à construire l'objet sans inférence :
ils ne prouvent ni accès à Astra ni compatibilité effective de ce modèle avec
ce mode d'API. Une connexion réelle exige encore ces vérifications.

## Résultats et limites

`hermes_worker.py` exécute les appels de la boucle native
`AIAgent.run_conversation` dans le Python séparé de Hermes. Il reçoit un message,
l'historique natif et les identifiants de session/tour par stdin, puis retourne
les messages, le texte et les indicateurs d'échec/interruption par stdout. Il
vérifie que le profil MCP est lié au même tour. L'authentification vient de
`PROMETHEE_OPENAI_API_KEY` ou de la résolution native Hermes explicitement choisie,
jamais du message JSON ; les erreurs d'entrée et les
exceptions retournent une catégorie sans reproduire leur texte brut.

`ConversationStore` conserve maintenant les messages utilisateur et l'historique
natif dans la même base que les tours, sous le schéma 6. L'ouverture d'une
correction et la validation d'une réponse sont transactionnelles : un ancien
résultat ne peut pas remplacer l'historique après une nouvelle demande. Un
redémarrage retrouve le dernier contexte terminé et les messages restés sans
réponse, sans réémettre une action. Les résultats échoués sont exclus du contexte.

L'hôte `chat.py` gère le lancement, l'échéance, l'arrêt du processus et la diffusion
sérialisée des réponses textuelles. Le worker seul ne crée pas de monde, n'ouvre
pas de tour et ne décide pas qu'une action corporelle a réussi. Le [diagnostic
vocal](voice.md) réutilise ce même hôte ; modèles audio et périphériques réels
restent à qualifier.

Le script [qualify_hermes_loop.py](../experiments/agent/qualify_hermes_loop.py)
utilise le vrai Hermes et le vrai transport MCP, avec un fournisseur déterministe
sur la boucle locale. Il vérifie deux lectures du monde, la présence du premier
échange dans l'appel suivant, puis une proposition volontairement retardée par
une correction. Celle-ci est refusée malgré une révision fraîche et sa réponse
est écartée ; aucun événement d'action n'est créé. Un dernier appel simule un
refus HTTP 401 pour vérifier la remontée de l'échec. Ce fournisseur est un doublon
de test explicite, sans raisonnement ni accès à Astra.

```sh
python experiments/agent/qualify_hermes_loop.py --output .local/essai-hermes-neuf --hermes-python CHEMIN_PYTHON_HERMES --hermes-root CHEMIN_HERMES
```

Le Python appelant doit avoir l'extra `agent` installé. Le script conserve les
sources, profils, messages et résultats dans le dossier neuf indiqué. Ces données
de qualification sont exclues de toute mémoire personnelle. La première série
réussie avec historique, `.local/hermes-loop-qualification-02`, a pris environ
10,7 secondes par appel, incluant un nouveau processus et l'initialisation de
Hermes. Ce délai ne mesure pas la vitesse d'Astra et reste trop élevé pour la voix.
La série `.local/hermes-loop-qualification-06` utilise le stockage transactionnel
du schéma 6 : deux tours terminés, réponse obsolète exclue de l'historique suivant
et erreur fournisseur conservée comme échec. Elle utilise toujours le fournisseur
de test local, pas Astra.
Hermes sonde aussi `/api/show` sur cet endpoint local ; le doublon répond 404 et
les appels de conversation restent sur le protocole explicitement choisi.

Le 15 septembre 2026, sous Windows 11 :

- Les tests CPU vérifient la provenance, le refus de création implicite,
  l'absence de téléportation, la retransmission et le contrôleur absent.
- Le test optionnel utilise deux vrais processus MCP : découverte, entier
  mal typé refusé, soumission/relecture, opération de feedback absente,
  fermeture puis réouverture du transport et annulation avant dispatch.
- `.local/runtime-mcp-01/mcp-qualification.json` contient une demande réelle de
  posture à ARDY (graine initiale 1301), sa retransmission sans doublon, puis
  `completed` avec observation cinématique après **9,164 s**. Il ne s'agit pas
  d'une décision prise par un modèle de raisonnement.
- `.local/hermes-profile-qualification-02/qualification.json` conserve la
  découverte par le vrai client Hermes, puis sa lecture du même monde et de
  cette exécution confirmée. Ces données techniques sont exclues de toute
  ingestion dans la future mémoire personnelle.
- L'accès configuré localement à `https://api.openai.com/v1` a répondu **401**
  lors de la liste des modèles. Aucun appel d'inférence, aucun remplacement
  d'Astra et aucune copie de jeton Codex n'ont été effectués.

L'hôte peut ouvrir un tour avec `ExecutionService.begin_turn(timeout=60)`, puis
lancer ce même serveur avec `--turn-id IDENTIFIANT_RETOURNE`. Le serveur est lié
à ce tour pour sa durée de vie ; le modèle ne peut pas choisir un autre tour
dans les arguments MCP. Un nouveau message utilisateur ouvre un nouveau tour,
qui invalide les mutations de l'ancien serveur. Fermer un tour via `end_turn`
invalide aussi toute nouvelle proposition tardive. Ces opérations sont réservées
à l'hôte, absentes des outils MCP. Le lancement sans `--turn-id` ci-dessus reste
un diagnostic manuel, sans cette protection conversationnelle.

Les tests du vrai transport stdio ouvrent deux processus successifs et vérifient
qu'un ancien serveur ne peut plus soumettre ni arrêter une action après correction,
même après relecture du monde. Les tests CPU couvrent également échéance, fin du
tour, remplacement de l'hôte et migration v4 → v5. Aucun de ces tests n'est une
conversation avec Astra ni une validation de diffusion vocale.

Le script [qualify_hermes_host.py](../experiments/agent/qualify_hermes_host.py) vérifie
le vrai Hermes avec `TextHost`, puis la commande publique après redémarrage. Il
requiert les mêmes arguments de chemins que `qualify_hermes_loop.py`. Le fournisseur
reste un doublon local : lecture du monde, correction pendant un appel lent,
délai dépassé et erreur HTTP 401. Les résultats et sources restent dans le dossier
neuf de qualification et sont exclus de la mémoire personnelle.

La série `.local/hermes-host-qualification-04` termine les cinq vérifications :
lecture en 11,11 s, arrêt de l'ancien processus lors d'une correction en 140 ms,
échéance de 15 s respectée à environ 30 ms près, erreur fournisseur et reprise
via `chat`. Ces délais incluent l'initialisation froide de Hermes ; ils ne
mesurent pas la latence d'Astra. Aucun événement d'action corporelle n'est créé
dans cette série, qui vérifie l'hôte et ses lectures MCP.

Les essais ont révélé que Hermes peut fusionner deux messages utilisateur sans
réponse en les séparant par deux sauts de ligne. Le stockage accepte cette fusion
exacte de messages connus et conserve le contexte natif ; une simple sous-chaîne
ou un message différent ne suffit pas. Les tests de sous-processus couvrent aussi
l'arrêt des descendants après perte du parent, la récupération du verrou après
une coupure et la fermeture sur échéance.

Les essais réels de posture et d'interruption sont décrits plus bas. La
qualification des déplacements et des interactions supplémentaires reste liée
aux capacités et aux limites mesurées du contrôleur.
Le fournisseur de test ne prouve aucune qualité de raisonnement. T07 conserve
également ses limites de déplacement ; la conversation vocale reste dans T11.

## Essai réel de la boucle native avec Astra

Le 15 septembre 2026, `.local/hermes-astra-access-02` a vérifié un premier appel
réel avec `provider=openai-codex`, `model=gpt-6-astra` et
`api_mode=codex_responses`. Seuls les cinq outils du monde étaient disponibles.
Astra a lu le monde vide, signalé l'absence de confirmation du corps et n'a
soumis aucune action. Le premier essai, avec un profil placé en dehors de la
racine native, avait échoué à résoudre l'authentification ; il reste archivé.

La série `.local/hermes-codex-host-01` utilise ensuite `open_text_host`, le
processus public du worker et un monde `qualification` neuf. L'hôte est fermé
puis rouvert entre les trois messages :

| Vérification | Observation | Durée totale |
|---|---|---|
| Conversation seule | « bonjour », aucun appel d'outil | 14,71 s |
| Lecture du monde | Un appel `read_world`, état corporel non confirmé correctement distingué | 21,77 s |
| Historique après redémarrage | Premier message cité exactement, aucun nouvel appel d'outil | 15,19 s |

Les profils, sources du raccord, messages natifs et résultats sont conservés
hors Git. Aucun fichier `auth.json` n'a été créé dans les trois profils de cet
essai. Aucune exécution corporelle n'a été demandée. Ces durées incluent le
démarrage froid de Hermes et ne sont pas des latences de voix interactive.
Ces données techniques restent exclues de la mémoire personnelle.

Pour reproduire ces trois appels réels avec un dossier de sortie neuf :

```sh
python experiments/agent/qualify_hermes_codex.py --output .local/essai-astra-neuf --hermes-python CHEMIN_PYTHON_HERMES --hermes-root CHEMIN_HERMES --hermes-auth-root RACINE_DONNEES_HERMES --model gpt-6-astra
```

Ce script n'active ni microphone ni initiative et ne lance aucun contrôleur
corporel. Il vérifie le raccord réel et la reprise de contexte, pas l'ensemble
des critères T09–T12.

## Astra, corps et interruption : essais réels

Les dossiers `.local/astra-body-qualification-01` et `-02` conservent les
messages, appels d'outils, événements, poses horodatées, sources du raccord et
relectures VRM. Ils utilisent des mondes `qualification` neufs, Astra via Hermes
natif, ARDY et l'avatar préparé ; aucun contrôleur factice ne produit les résultats.

Dans le premier essai, graine moteur **128123**, Astra vérifie les capacités puis
soumet `arms_raised`. L'exécution est confirmée après **10,26 s** ; sa réponse
arrive en **42,75 s** au total et distingue explicitement `accepted` de
`completed`. Une relecture sans nouvelle action retrouve le résultat confirmé.
La demande de prendre un objet absent est refusée après lecture du monde, sans
soumission au corps. La relecture de 164 poses montre les bras monter puis rester
au-dessus de la tête ; les poses intermédiaire et finale ont été inspectées.

L'annulation suivante, pendant la préparation, a mis en évidence une lacune :
le nouveau tour ne connaissait plus l'identifiant de l'action `standing`
interrompue et demandait de le fournir, alors que le contrôleur avait enregistré
`cancelled`. Cela a motivé les résultats récents ajoutés à `read_world`.

Le second essai, graine **138123**, confirme à nouveau les bras levés, puis
interrompt `standing` à sa **pose 10 pendant la lecture du mouvement**. Le test
injecte l'arrêt utilisateur directement dans le service du corps et remplace
le tour de conversation en cours. Il ne mesure donc pas une commande d'arrêt
vocale ni le délai de décision du modèle.

- Le contrôleur confirme `cancelled` **179,85 ms** après la demande d'arrêt.
- La pose Core, les objets et l'apparence VRM restent exactement identiques
  entre le point d'arrêt demandé et le résultat confirmé.
- Le nouveau tour d'Astra retrouve `retour-debout-01` via les résultats récents,
  le relit et rapporte correctement l'annulation, sans prétendre que `standing`
  a été atteint ni demander un identifiant à l'utilisateur.
- La réponse après interruption prend **30,02 s**, démarrage froid inclus.
  Seules deux exécutions existent : les bras levés terminés et le retour debout
  annulé. Aucune action obsolète ne repart.

La relecture de 987 poses conserve la chronologie observée entre les deux
actions ; les poses autour de l'arrêt ont été inspectées. Ces essais valident
la concordance des outils, des paroles et de ces postures cinématiques. Ils ne
prouvent ni l'équilibre physique, ni toutes les interactions possibles, ni une
latence adaptée à une conversation vocale.

## Piste Codex vérifiée, raccord non activé

Le 15 septembre 2026, le CLI Codex **0.153.1** indique une connexion ChatGPT
existante. Une connexion stdio au serveur officiel, limitée à `initialize`,
`initialized` et `model/list`, renvoie **`gpt-6-astra`** dans son catalogue.
Le rapport local `.local/codex-model-access.json` conserve les identifiants de
modèles et précise qu'aucun tour d'inférence n'a été lancé. Aucun jeton n'a été
lu ou copié par le diagnostic. Ce résultat établit la présence d'Astra dans le
catalogue de ce runtime ; il ne valide ni une réponse du modèle, ni l'accès API
précédemment refusé, ni le pilotage du monde.

Hermes installé à la révision `cd297653fa4fac85f45f7d3ad8e361db0f14e9be`
possède un mode optionnel `codex_app_server`. Il délègue la boucle d'outils à
Codex. Sa documentation locale décrit une migration des plugins et des MCP
personnels ainsi qu'un accès aux outils de développement. L'activer tel quel
ne satisfait donc pas le profil limité à Promethee de T09.

Deux détails du code installé empêchent aussi de traiter ce mode comme un
simple changement de fournisseur : `CodexAppServerSession.ensure_started()`
ne transmet que `cwd` à `thread/start`, et `run_turn()` transmet uniquement le
message courant à `turn/start`. Ces requêtes ne sélectionnent pas explicitement
le modèle et ne transportent pas l'historique fourni à l'hôte Promethee. Or cet
hôte recrée actuellement son processus Hermes à chaque tour. Les vérifier est
nécessaire avant de réutiliser ce mode pour une conversation persistante.

Le [protocole officiel App Server](https://learn.chatgpt.com/docs/app-server)
et les schémas générés par le CLI installé offrent des paramètres de modèle,
de configuration et de session éphémère. La
[configuration officielle](https://learn.chatgpt.com/docs/config-file/config-reference)
permet notamment de désactiver le terminal et la lecture des instructions de
projet. Ces possibilités restent à qualifier ensemble : absence d'outils et
de contexte personnels hérités, modèle demandé réellement utilisé, continuité
des échanges, outils monde/mémoire liés au tour courant, interruption et
fermeture de tous les processus. La découverte du catalogue ne suffit pas à
cocher ces critères. Le chemin `chat` publié utilise la boucle native Hermes,
avec la qualification réelle décrite plus haut ; `codex_app_server` n'est pas
activé. Aucune migration de configuration personnelle n'est effectuée
automatiquement.
