# Pont Hermes

Le pont local expose cinq outils et utilise le même runtime que le contrôleur
cinématique. Il ne lance aucun modèle de raisonnement. T09 reste ouvert : la
conversation réelle avec Astra n'est pas encore raccordée. Le runtime sait
désormais invalider les propositions d'un ancien tour ; la future boucle Hermes
doit encore ouvrir et fermer ces tours. Ne pas activer une session autonome avec ce seul pont.

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
personnelle de l'avatar. La restriction des outils natifs de la future boucle de
conversation reste à vérifier avant de l'activer.

## Résultats et limites

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

Restent nécessaires : accès effectif à Astra, profil conversationnel limité,
raccord des tours à la boucle Hermes et essais réels de correction utilisateur
et de délai fournisseur. Le pont seul ne
satisfait pas ces critères. T07 conserve également ses limites de déplacement.
