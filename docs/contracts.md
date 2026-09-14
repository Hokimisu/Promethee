# Contrats exécutables — monde version 3

Ces exemples décrivent l'API Python locale. Aucun endpoint HTTP, WebSocket ou MCP n'est encore livré.

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

## Migration explicite

Ouvrir une ancienne base v1 ou v2 ne la modifie pas. Pour la migrer, choisir une sauvegarde qui n'existe pas :

```sh
uv run promethee --data-dir .local/ancien-monde migrate --backup .local/sauvegardes/avant-v3.sqlite3
```

La sauvegarde SQLite est copiée et vérifiée pendant que les écritures sont exclues, avant la migration transactionnelle. Les données sans origine deviennent `legacy`, leur révision commence à zéro ; leur ID de monde, historique et plans sont préservés. Une nouvelle migration d'une base déjà à jour ne fait rien. Une sauvegarde existante n'est jamais écrasée et une version inconnue reste refusée.

Les anciens plans restent exécutables dans les bases `legacy`. Ils ne deviennent pas pour autant des expériences d'agent : créer une base `session` distincte pour le futur agent.

Les noms d'objets identifient des instances ; les noms d'assets identifient des capacités du catalogue. Un `world_id` unique évite de mélanger les journaux de deux mondes exportés dans le même coffre.

## Exécutions du corps

`ExecutionService(runtime)` propose `get_world()`, `supported_actions()`, `submit(request_id, expected_revision, action)`, `get(request_id)`, `cancel(request_id)` et `events(after=0, limit=100)`. Cette API est livrée sur CPU ; aucun pilote 3D n'est encore intégré. Les tests injectent leur propre contrôleur `logical-test` dans une fixture.

`submit` persiste une enveloppe comportant l'ID, la révision attendue et l'action. Il ne déplace rien. Une retransmission strictement identique retourne l'état courant avec `replayed: true`, avant tout contrôle de révision. Un ID avec une autre enveloppe est refusé, même si la précédente exécution est terminée. Un nouvel essai utilise un nouvel ID.

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

## Pilote et observations

Seul le pilote appelle `acquire_controller(source=..., supported_actions=[...], lease_seconds=5.0)`. `logical-test` exige une fixture ; `kinematic` et `physics` exigent une session. Ces étiquettes décrivent la provenance déclarée par le code du pilote ; elles ne prouvent pas à elles seules la validité d'une intégration. Le handle retourné et ses opérations ne doivent jamais être exposés à un modèle comme outils.

- `heartbeat()` renouvelle la propriété exclusive. Un second propriétaire est refusé ; une ancienne session ne peut pas renouveler la nouvelle.
- `reconcile(observation, stopped=True)` atteste l'arrêt et fournit un état complet, sans exécution active.
- `claim_next()` persiste l'envoi avant de remettre une demande au pilote ; aucun appel moteur n'a lieu dans une transaction SQLite.
- `claim_cancellation()` remet une demande d'arrêt une seule fois.
- `feedback(request_id, sequence, status, observation=..., error=...)` fournit le retour ; la session est attachée au handle. Les séquences répétées ou anciennes, sessions périmées et retours après un état terminal sont ignorés.
- `release()` abandonne la propriété et interrompt les exécutions actives.

L'observation actuelle comprend exactement `avatar` et `objects`, avec les champs du monde logique. Les positions sont finies, dans les bornes, et les références aux objets tenus ou occupés doivent être cohérentes. Ce format provisoire ne contient pas les articulations : T07 l'étendra après l'essai moteur. `completed` et l'accusé `cancelled` exigent une observation complète ; `failed` exige une cause. Un échec sans observation rend le corps non confirmé.

Le champ `body` du monde contient `status` (`confirmed` ou `unconfirmed`), `observed_at` et `source`. `ExecutionService.get_world()` et la CLI `world` appliquent les expirations avant lecture. `Runtime.snapshot()` fournit seulement le dernier état persisté. Une lecture qui constate la perte du pilote peut donc modifier le statut et la révision, sans inventer une nouvelle pose.

## Arrêt et récupération

`cancel` termine immédiatement une demande non envoyée. Après envoi, il pose `cancel_requested` et une échéance (deux secondes par défaut, configurable à la création du service). Répéter l'appel ne repousse pas cette échéance. La dernière pose confirmée est conservée pendant l'attente. Une fin et une annulation concurrentes produisent un seul résultat terminal selon l'ordre enregistré.

L'expiration du bail ou du délai d'arrêt produit `interrupted`, conserve la dernière observation et marque `body.status` comme `unconfirmed`. Les nouvelles mutations sont refusées. L'expiration est évaluée lors des opérations du service ; le futur pilote continu doit appeler le service pendant son fonctionnement. Aucune tâche cachée ni thread moteur n'est créé par cette API.

Pour reprendre après une panne : laisser expirer le bail de l'ancien pilote, acquérir un nouveau handle, obtenir et valider une observation complète du système effectivement arrêté, puis appeler `reconcile`. Après une annulation expirée avec un pilote encore propriétaire, ce même handle peut réconcilier une fois l'arrêt acquis. Ne pas recopier la destination souhaitée comme observation. L'ancienne exécution reste interrompue ; soumettre ensuite une nouvelle requête avec un nouvel ID et la révision relue. Aucun accès manuel à SQLite n'est requis.

La migration v2 → v3 ajoute les tables d'exécution et initialise le corps comme non confirmé, sans modifier l'origine ni la révision existantes. La migration v1 passe successivement par les deux étapes, sous la même sauvegarde et transaction.
