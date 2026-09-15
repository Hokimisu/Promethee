# Pont Hermes

Le pont local expose cinq outils du monde, plus quatre outils de mémoire lorsque
`--vault` désigne un coffre configuré. Il utilise le même runtime que le contrôleur
cinématique. La commande `chat` lance désormais la boucle native Hermes dans
son environnement séparé, avec historique persistant et interruption des appels.
T09 reste ouvert : ce raccord est vérifié avec un fournisseur de test local,
pas avec Astra. Il ne lance aucune initiative autonome.

## Conversation textuelle

Ouvrir d'abord une base `session` avec le contrôleur du [guide moteur](motion-validation.md),
ou créer un monde vide sans corps avec `promethee --data-dir CHEMIN_SESSION init-session`.
Pour ajouter la mémoire, initialiser un coffre neuf selon le [guide mémoire](memory.md),
puis ajouter `--vault CHEMIN_COFFRE` à `chat`. Les anciennes sessions non classées
peuvent converser mais ne sont pas admissibles à cette mémoire.
Une base existante doit être au schéma 7 ; arrêter ses processus avant d'appliquer
la [migration explicite](contracts.md). Installer l'extra `agent` dans le Python
de Promethee et utiliser l'installation Hermes 0.20.5 qualifiée ci-dessous.
Configurer `PROMETHEE_OPENAI_API_KEY` localement, sans la mettre dans Git ni dans
la commande. Le modèle et le mode d'API sont explicites, car leur compatibilité
avec l'accès Astra du compte n'est pas encore validée.

```sh
python -m promethee.cli --data-dir CHEMIN_SESSION chat --hermes-python CHEMIN_PYTHON_HERMES --hermes-root CHEMIN_HERMES --model MODELE_AUTORISE --api-mode chat_completions
```

Cette commande utilise par défaut `https://api.openai.com/v1` ; `--base-url`
permet un endpoint explicitement choisi et `--api-mode codex_responses` sélectionne
l'autre mode accepté par l'adaptateur. Aucun autre fournisseur ni modèle n'est
essayé automatiquement. Une clé absente ou un monde absent échoue avant l'appel.

Saisir un message par ligne. Un nouveau message invalide l'appel précédent avant
de fermer son processus, puis démarre le nouvel échange. `/cancel` coupe seulement
la réponse en cours ; `/quit` ferme le chat. Ces opérations n'annulent pas une
action corporelle déjà acceptée. Un arrêt du corps passe par son outil d'annulation.
Les sorties indiquent `completed`, `failed` ou `interrupted` pour **la réponse**,
sans les confondre avec les états d'exécution du corps. Le délai maximal vaut
60 secondes par défaut (`--timeout`). Aucun appel au modèle n'est fait pendant
l'attente d'un message.

Un verrou détenu par le système autorise un seul hôte de conversation par monde.
Le redémarrage ferme les anciens tours, conserve les messages restés sans réponse
et ne réémet aucune action. Chaque appel reçoit un profil neuf dans
`conversation-profiles/`, lié au tour et limité aux cinq outils du monde, ou neuf
avec la mémoire. Ces profils
contiennent des données privées ; ils ne sont pas des coffres à importer.
Le contexte natif conservé dans la base fait autorité pour la reprise.

Sous Windows, le processus est créé suspendu, attaché à un groupe dont la fermeture
termine aussi ses descendants, puis démarré. Cela couvre également le lanceur de
l'environnement virtuel et un pont MCP survivant à son parent. Les interfaces
sont celles des [Job Objects](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information)
et de [CREATE_SUSPENDED](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags).
Sous Linux, l'appel possède son propre groupe de processus. Le pilote corporel
indépendant n'appartient pas à ce groupe.

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

## Configuration Hermes vérifiée

Installation locale conservée sans modification : Hermes **0.20.5**, Python
3.11.15, révision `cd297653fa4fac85f45f7d3ad8e361db0f14e9be` incluant un commit
local. Le dépôt officiel plus récent a aussi été consulté à la révision
`2179a279ae04bfadf8efbc49a01ca0abfb738000` ; il n'a pas remplacé cette installation.

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

`hermes_worker.py` exécute maintenant un appel de la boucle native
`AIAgent.run_conversation` dans le Python séparé de Hermes. Il reçoit un message,
l'historique natif et les identifiants de session/tour par stdin, puis retourne
les messages, le texte et les indicateurs d'échec/interruption par stdout. Il
vérifie que le profil MCP est lié au même tour. La clé vient uniquement de
`PROMETHEE_OPENAI_API_KEY`, jamais du message JSON ; les erreurs d'entrée et les
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

Restent nécessaires : accès effectif à Astra et conversations variées avec ce
modèle pour vérifier ses décisions et la restitution des résultats corporels.
Le fournisseur de test ne prouve aucune qualité de raisonnement. T07 conserve
également ses limites de déplacement ; la conversation vocale reste dans T11.
