# Contrats exécutables — monde version 12

Ces exemples décrivent l'API Python locale. Le rendu utilise HTTP/WebSocket sur l'interface de boucle locale. `run` propose des boutons de pilotage qui passent par le service d'exécution. Le [pont MCP stdio](hermes-setup.md) expose cinq opérations de ce même service et, avec un coffre configuré, quatre outils de mémoire ; aucune API REST d'action n'est livrée.

## Pilotage manuel

`uv run promethee catalog` affiche les capacités logiques du catalogue sans ouvrir de base.
`uv run promethee --data-dir .local/manual act --request-id commande-1 --file action.json`
exécute une action JSON UTF-8 au format décrit ci-dessous, sans créer de plan.

Le code de sortie vaut `0` pour une réussite, `1` pour un rejet métier et `2` pour une erreur d'entrée (fichier, JSON ou ID). Une retransmission conserve le résultat et le code de sortie de l'action enregistrée. Les erreurs de stockage restent des erreurs techniques. Un ID doit être réutilisé pour retransmettre la même demande, pas pour une nouvelle tentative après changement du monde.

## Commande

```python
from promethee.runtime import Runtime

runtime = Runtime(".local/promethee/world.sqlite3")
result = runtime.execute(
    "spawn-chair-001",
    {
        "kind": "spawn",
        "args": {"object_id": "chair-1", "asset": "chair", "position": [1, 0]},
    },
)
```

Les identifiants de commande et d'objet utilisent 1 à 64 caractères : une lettre minuscule initiale, puis lettres minuscules, chiffres, `_` ou `-`. Le préfixe de commande `activity-` est réservé au runtime.

| Action | Arguments exacts | Préconditions principales |
|---|---|---|
| `spawn` | `object_id`, `asset`, `position` | Asset connu, ID absent, moins de 32 objets |
| `move` | `position` | Avatar debout ; l'objet tenu suit |
| `write` | `object_id`, `text` | Pancarte accessible ; texte de 1 à 500 caractères |
| `take` | `object_id` | Objet mobile et accessible, mains libres, pas l'assise occupée |
| `place` | `position` | Objet tenu, destination accessible |
| `sit` | `object_id` | Chaise accessible, avatar debout, chaise non tenue |
| `stand` | Aucun (`{}`) | Avatar assis |

`position` est `[x, y]`, en mètres sur le plan du sol. Chaque coordonnée doit être finie et comprise entre -5 et 5. Les booléens sont refusés comme coordonnées. La portée logique est une distance euclidienne maximale d'un mètre. Il n'y a pas d'évitement de collisions.

Les champs inconnus sont rejetés. Les textes, noms d'assets et arguments ne sont jamais interprétés comme du code.

## Résultat et retransmission

```json
{"ok": true, "replayed": false}
```

Une action invalide retourne `ok: false` et `error` sans modifier le monde. Son rejet est enregistré. Une même requête réémise retourne le résultat enregistré avec `replayed: true`. Réutiliser son ID avec un autre contenu lève `ActionError`. Pour réessayer après modification de la situation, fournir un nouvel ID.

Les erreurs de sérialisation ou d'identifiant surviennent avant l'enregistrement. Les erreurs de stockage sont propagées ; elles ne doivent pas être annoncées comme des résultats métier.

`ok: true` signifie uniquement que la transition **logique** a été validée et persistée. Aucun succès visuel ou physique n'est impliqué.

## Activité

`start_activity(id, steps)` conserve le plan complet et initialise son curseur. Le plan est d'abord vérifié sur une copie jetable du monde actuel ; cette vérification ne garantit pas sa réussite après des modifications ultérieures du monde.

- ID jusqu'à 40 caractères ; de 1 à 100 étapes.
- `advance(id)` réalise au plus une étape et sauvegarde le curseur atomiquement.
- `set_paused(id, True)` suspend ; `set_paused(id, False)` reprend.
- États : `running`, `paused`, `completed`, `failed`.
- Avancer une activité suspendue, terminée ou échouée n'a aucun effet.
- Une même activité ne peut pas être remplacée par un autre plan sous le même ID.

La pause des plans intervient entre deux actions logiques instantanées. Les plans ne sont pas branchés aux exécutions du corps ci-dessous.

## Stockage et observation

`snapshot()` retourne le monde courant avec son `schema_version`, son `world_id`, l'avatar et les objets. `events()` expose, dans l'ordre, l'identifiant de requête, l'action, son résultat et un horodatage UTC.

Le snapshot comporte aussi `data_origin` (`fixture`, `session`, `legacy`) et `revision`. La révision augmente uniquement lors d'une modification effective du monde, dans la même transaction. Les lectures, rejets, actions sans effet et retransmissions ne l'augmentent pas.

`Runtime(path)` crée un monde `fixture` lorsqu'il n'existe pas ; `Runtime(path, data_origin="session")` crée explicitement une session vide. Rouvrir une base conserve son origine ; une origine explicitement différente est refusée. `require_session()` refuse les données `fixture` et `legacy`. Les commandes logiques et plans de démonstration refusent les mondes `session`, qui attendent le contrôleur du corps.

`Runtime(path, create=False)` ouvre uniquement une base existante contenant un
monde à jour, sans créer de dossier ni initialiser un fichier SQLite vide. Le
serveur MCP utilise cette option et exige ensuite `require_session()`.

## Migration explicite

Ouvrir une ancienne base v1 à v11 ne la modifie pas. Pour la migrer, arrêter tous
les processus qui utilisent la base et choisir une sauvegarde qui n'existe pas :

```sh
uv run promethee --data-dir .local/ancien-monde migrate --backup .local/sauvegardes/avant-v12.sqlite3
```

La sauvegarde SQLite est copiée et vérifiée pendant que les écritures sont exclues, avant la migration transactionnelle. Les données sans origine deviennent `legacy`, leur révision commence à zéro ; leur ID de monde, historique et plans sont préservés. Une nouvelle migration d'une base déjà à jour ne fait rien. Une sauvegarde existante n'est jamais écrasée et une version inconnue reste refusée.

Les anciens plans restent exécutables dans les bases `legacy`. Ils ne deviennent pas pour autant des expériences d'agent : créer une base `session` distincte pour le futur agent.

Les noms d'objets identifient des instances ; les noms d'assets identifient des capacités du catalogue. Un `world_id` unique évite de mélanger les journaux de deux mondes exportés dans le même coffre.

## Exécutions du corps

`ExecutionService(runtime)` propose `get_world()`, `supported_actions()`, `submit(request_id, expected_revision, action)`, `get(request_id)`, `cancel(request_id)` et `events(after=0, limit=100)`. Cette API reste testable sur CPU. Le pilote ARDY optionnel expose actuellement `move` et `posture`, cette dernière avec l'argument exact `name` (`standing` ou `arms_raised`). L'action logique `act` n'accepte pas `posture`. Les tests injectent leur propre contrôleur `logical-test` dans une fixture ; les essais ARDY et la commande `run` sont décrits dans [la qualification T07](motion-validation.md).

`submit` persiste une enveloppe comportant l'ID, la révision attendue et l'action. Il ne déplace rien. Une retransmission strictement identique retourne l'état courant avec `replayed: true`, avant tout contrôle de révision. Un ID avec une autre enveloppe est refusé, même si la précédente exécution est terminée. Un nouvel essai utilise un nouvel ID.

`get_world()` expose aussi `command_revision`, calculée à partir de `revision`
moins le compteur persistant `idle_pose_updates`. Le schéma 12 initialise ce
compteur à zéro : il ne requalifie aucune observation historique. Le snapshot
brut conserve les deux compteurs, sans stocker la valeur dérivée.

Pour commander pendant les gestes de présence, utiliser
`submit(request_id, action=action, expected_command_revision=world["command_revision"])`.
Il faut fournir exactement une garde : `expected_revision` conserve le contrôle
strict de chaque image observée ; `expected_command_revision` tolère uniquement
les changements de pose et de cadrage corporel issus de `observe_idle`. L'action
est vérifiée contre **la pose actuelle**, dans la transaction de soumission.
Il n'y a ni réutilisation de l'ancienne pose ni nouvelle tentative automatique.
Les reçus enregistrent `validated_revision` et `validated_command_revision` pour
identifier le monde examiné, y compris lorsqu'une demande est rejetée.

Seuls la pose du même squelette, la position de l'avatar, la date d'observation
et les corrections animées du même asset préparé sont exclus de cette garde.
Un changement d'objet, de prise, d'assise, d'identité d'apparence, de provenance,
de confirmation du corps ou de tour la périme. Un objet modifié puis remis
comme avant la périme aussi. Les observations d'une action explicite et les
réconciliations restent strictes. Le contrôle de portée, les capacités, le bail
du contrôleur, la priorité de l'action active et la clôture des tours restent
vérifiés. Le mouvement avec objet tenu n'est pas qualifié par ce contrat.
L'[essai réel Hermes et ARDY](command-revision.md) distingue admission pendant
la présence, erreur de format corrigée et résultat terminal du contrôleur.

Une seule exécution peut être active. Une nouvelle mutation concurrente reçoit `rejected` avec le code `busy`. Le monde doit être confirmé par un contrôleur actif ; sinon le code est `controller_unavailable`. Les autres rejets comprennent `revision_conflict`, `invalid_action` et `legacy_world`. Le chemin logique, y compris `act` et les plans, refuse les sessions et les fixtures possédées par un contrôleur.

| État | Sens |
|---|---|
| `accepted` | Intention enregistrée, sans résultat attesté |
| `running` | Début ou progression confirmé par le pilote |
| `completed` | Fin confirmée après `running`, avec observation complète |
| `failed` | Cause d'échec connue ; observation éventuellement disponible |
| `cancelled` | Annulation avant envoi, ou arrêt confirmé avec observation |
| `interrupted` | Résultat inconnu, à réconcilier |
| `rejected` | Demande refusée avant envoi |

Les cinq derniers états sont terminaux. Les événements paginés portent `seq`, `kind`, `recorded_at` et l'exécution, contenant sa requête, sa session de contrôleur et sa provenance. Une observation reçue est conservée avec `observed_at`. Les événements, le résultat et le monde sont écrits dans la même transaction.

## Diffusion vocale

Le schéma 11 ajoute `speech_delivery` dans les enregistrements de conversation.
La migration sauvegarde d'abord la base, préserve les messages et initialise
ce champ à `null` : les anciens textes ne prouvent aucune diffusion audio.
Le seul hôte vocal peut enregistrer préparation, lecture, fin ou interruption
pour une réponse texte terminée et sa génération audio. Un retour d'une autre
génération ou la réouverture d'un résultat terminal est refusé.

Le pont `read_world` expose jusqu'à huit comptes rendus récents dans
`recent_speech_deliveries`, séparément des exécutions corporelles. Ces lectures
ne modifient ni le corps ni l'historique natif. Les états et limites sont décrits
dans le [contrat vocal](voice.md). Un compte rendu ne prouve pas les mots entendus.

## Pilote et observations

Le schéma 10 ajoute `appearance`, nul tant qu'aucune pose d'apparence préparée
n'a été observée. Une valeur contient l'asset épinglé, son échelle, le mode
d'adaptation, les mains alignées, les rotations normalisées et le décalage du
bassin pour une seule image. L'empreinte canonique `core_pose_sha256` doit
correspondre à la pose Core de la même observation. Ce contrat de stockage ne
remplace pas les contrôles géométriques du préparateur.

Le pilote peut omettre `appearance` lorsqu'aucun checkpoint visible n'existe.
Une fois une apparence préparée enregistrée, un retour qui l'omet ou la remet
à `null` est refusé : il ne peut laisser une correction ancienne associée à une
nouvelle pose Core. Un objet tenu doit utiliser une main figurant dans les
alignements du checkpoint. Corps, objets, apparence et événement sont écrits
dans la même transaction. La validation de stockage reste utilisable sans NumPy.

La migration 9 → 10 conserve une sauvegarde exclusive et ajoute seulement
`appearance: null`. Elle n'invente pas l'apparence des poses historiques.
Arrêter les processus utilisant une base avant de la migrer :

```sh
uv run promethee --data-dir .local/ma-session migrate --backup .local/ma-session-avant-v10.sqlite3
```

Le pilote avec préparation d'apparence conserve ces checkpoints dans les
observations. La [qualification initiale sur une copie de session](avatar-foot-contact.md#sauvegarde-de-la-pose-visible)
reste distincte des essais ultérieurs en direct décrits dans le
[guide moteur](motion-validation.md).

Depuis le schéma 9, les objets peuvent aussi porter une
[pose 3D et un attachement à la main](spatial-objects.md). Ces champs sont
validés et persistés avec l'observation complète ; ils ne sont pas ajoutés
aux objets logiques historiques par la migration.

Seul le pilote appelle `acquire_controller(source=..., supported_actions=[...], lease_seconds=5.0)`. `logical-test` exige une fixture ; `kinematic` et `physics` exigent une session. Ces étiquettes décrivent la provenance déclarée par le code du pilote ; elles ne prouvent pas à elles seules la validité d'une intégration. Le handle retourné et ses opérations ne doivent jamais être exposés à un modèle comme outils.

- `heartbeat()` renouvelle la propriété exclusive. Un second propriétaire est refusé ; une ancienne session ne peut pas renouveler la nouvelle.
- `reconcile(observation, stopped=True)` atteste l'arrêt et fournit un état complet, sans exécution active.
- `observe_idle(observation)` publie une pose de présence validée hors exécution, sans attester l'arrêt ni renouveler le bail. Une action active est prioritaire. Seules les différences corporelles admissibles conservent `command_revision`.
- `claim_next()` persiste l'envoi avant de remettre une demande au pilote ; aucun appel moteur n'a lieu dans une transaction SQLite.
- `claim_cancellation()` remet une demande d'arrêt une seule fois.
- `feedback(request_id, sequence, status, observation=..., error=...)` fournit le retour ; la session est attachée au handle. Les séquences répétées ou anciennes, sessions périmées et retours après un état terminal sont ignorés.
- `release()` abandonne la propriété et interrompt les exécutions actives.

L'observation comprend `avatar` et `objects`, avec les champs du monde logique, et `pose` pour un pilote `kinematic` ou `physics`. Seul le pilote `logical-test` peut omettre cette pose. Les positions sont finies, dans les bornes, et les références aux objets tenus ou occupés doivent être cohérentes. `completed` et l'accusé `cancelled` exigent une observation complète ; `failed` exige une cause. Un échec sans observation rend le corps non confirmé.

`pose` est aussi conservée à la racine du snapshot, initialement `null`. Son format exact est `{skeleton, positions, rotations}` : `skeleton` vaut `cskel27`, `positions` contient 27 triplets XYZ en mètres, Y vertical, et `rotations` contient 27 matrices globales 3 × 3 dans le même ordre articulaire que l'export T02. Les matrices sont finies, orthonormales et de déterminant +1 à une tolérance de 0,01. La projection XZ des hanches doit correspondre à `avatar.position` à 0,1 mm près. Ces contrôles détectent une observation incohérente ; ils ne certifient pas l'équilibre, la morphologie ou les contacts.

Le champ `body` du monde contient `status` (`confirmed` ou `unconfirmed`), `observed_at` et `source`. `ExecutionService.get_world()` et la CLI `world` appliquent les expirations avant lecture. `Runtime.snapshot()` fournit seulement le dernier état persisté. Une lecture qui constate la perte du pilote peut donc modifier le statut et la révision, sans inventer une nouvelle pose.

## Arrêt et récupération

Le schéma v5 ajoute `conversation`, initialement `null`. L'hôte conversationnel
de confiance ouvre un tour avec `ExecutionService.begin_turn(timeout=60)` ; le
monde conserve son identifiant et son échéance. Une correction ouvre un nouveau
tour. Le changement augmente la révision, sans annuler l'action du corps déjà
acceptée. `end_turn(turn_id)` ferme un tour encore valide ; une réponse expirée
ou issue d'un ancien tour est refusée. L'hôte doit ouvrir un nouveau tour à son
redémarrage et encore contrôler la fraîcheur au moment de diffuser de l'audio.

Le pont MCP peut être lié à cet identifiant par `--turn-id`. Cet argument vient
de l'hôte et ne figure pas parmi les arguments d'outils que le modèle choisit.
Une nouvelle soumission et une nouvelle annulation vérifient le tour dans la
même transaction que leur mutation : une lecture récente du monde ne permet
pas à un ancien pont de récupérer le droit d'agir. La retransmission exacte
d'une soumission existante reste une lecture idempotente de son résultat ;
elle n'est jamais réémise. Une annulation déjà demandée reste idempotente.
Les opérations manuelles et le pont de diagnostic sans tour restent disponibles.
La commande `chat` raccorde ces tours à la boucle native Hermes et gère les
processus ; sa qualification utilise un fournisseur de test local, pas Astra.

La migration v4 → v5 ajoute uniquement `conversation: null` et conserve poses,
requêtes et observations ; sauvegarde et rollback restent obligatoires. Fermer
les anciens processus avant de migrer, puis les relancer avec le même code.

La version 6 ajoute `conversation_turns`, vide lors de la migration, et invalide
l'éventuel tour conversationnel précédent. Elle conserve les observations,
exécutions et la propriété du contrôleur corporel ; elle n'importe aucun ancien
profil ni historique externe. La sauvegarde et le rollback couvrent aussi cette
création de table.

La version 7 ajoute le registre `memory_notes`, vide, et `session_kind: null`.
Les conversations, observations et exécutions antérieures restent conservées.
Une nouvelle session créée avec `session_kind="interactive"` peut recevoir un
coffre de mémoire ; les sessions non classées, de qualification, les fixtures
et les historiques en sont exclus. Rouvrir une base ne permet pas de changer
sa classification. La migration ne transforme donc aucun essai en souvenir.
Le [contrat mémoire](memory.md) décrit les sources, corrections, limites et la
reprise d'un export interrompu après son enregistrement SQLite.

La version 8 ajoute `initiative: null` sans activer d'appel. Une configuration
explicite conserve budget, pause et événements regroupés dans le monde. Réservation
et ouverture d'un tour autonome partagent une transaction ; une correction ou une
pause invalide ses outils. Voir le [contrat d'initiative](initiative.md).

`ConversationStore(service)` est réservé à l'hôte et exige une base `session`.
`begin(message, timeout=60)` conserve le message, marque les appels précédents
inachevés comme `interrupted` et ouvre le nouveau tour atomiquement. Il retourne
l'identifiant de tour, l'identifiant stable du monde utilisé comme session Hermes,
et le dernier contexte natif terminé, suivi des messages utilisateur restés sans
réponse. `finish(turn_id, result)` exige une réponse native réussie, non interrompue
et liée au tour encore valide ; l'historique et la fermeture du tour sont commis
ensemble. `abort` ferme uniquement cet appel, sans annuler une action du corps ni
modifier un tour plus récent. Les résultats natifs échoués ou périmés ne passent
pas dans le contexte suivant ; les messages utilisateur sont conservés.

Chaque enregistrement conserve le monde, l'origine, le message et sa date. Ce
stockage n'effectue ni résumé, ni entraînement, ni export automatique vers Obsidian.
Hermes peut fusionner exactement les messages utilisateur adjacents restés sans
réponse ; le contrôle reconnaît cette fusion connue sans accepter une simple
sous-chaîne. Le contexte transmis est limité à 512 Kio UTF-8 ; un dépassement échoue sans
troncature implicite. Une future gestion du contexte devra respecter les sources
de T10. La commande `chat` sérialise la diffusion du texte avec l'arrivée d'une
correction. La diffusion audio reste à raccorder ; le commit ne signifie pas « entendu ».

`cancel` termine immédiatement une demande non envoyée. Après envoi, il pose `cancel_requested` et une échéance (deux secondes par défaut, configurable à la création du service). Répéter l'appel ne repousse pas cette échéance. La dernière pose confirmée est conservée pendant l'attente. Une fin et une annulation concurrentes produisent un seul résultat terminal selon l'ordre enregistré.

L'expiration du bail ou du délai d'arrêt produit `interrupted`, conserve la dernière observation et marque `body.status` comme `unconfirmed`. Les nouvelles mutations sont refusées. L'expiration est évaluée lors des opérations du service ; le futur pilote continu doit appeler le service pendant son fonctionnement. Aucune tâche cachée ni thread moteur n'est créé par cette API.

Pour reprendre après une panne : laisser expirer le bail de l'ancien pilote, acquérir un nouveau handle, obtenir et valider une observation complète du système effectivement arrêté, puis appeler `reconcile`. Après une annulation expirée avec un pilote encore propriétaire, ce même handle peut réconcilier une fois l'arrêt acquis. Ne pas recopier la destination souhaitée comme observation. L'ancienne exécution reste interrompue ; soumettre ensuite une nouvelle requête avec un nouvel ID et la révision relue. Aucun accès manuel à SQLite n'est requis.

La migration v2 → v3 ajoute les tables d'exécution. La migration v3 → v4 ajoute `pose: null`, conserve l'origine et la révision, rend le corps non confirmé et retire la propriété de l'ancien pilote. Les exécutions encore `accepted` ou `running` deviennent `interrupted` avec la cause `schema_migrated` et un événement atomique. Les anciens succès restent historiques. Une observation 2D n'est jamais transformée en pose articulée. Les migrations depuis v1 ou v2 traversent les étapes nécessaires sous la même sauvegarde et transaction ; un échec annule aussi les interruptions et la révocation du pilote.
