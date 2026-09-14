# Contrats exécutables — monde version 2

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

La pause actuelle intervient entre deux actions logiques instantanées. L'interruption d'un mouvement en cours reste à implémenter avec le contrôleur moteur.

## Stockage et observation

`snapshot()` retourne le monde courant avec son `schema_version`, son `world_id`, l'avatar et les objets. `events()` expose, dans l'ordre, l'identifiant de requête, l'action, son résultat et un horodatage UTC.

Le snapshot comporte aussi `data_origin` (`fixture`, `session`, `legacy`) et `revision`. La révision augmente uniquement lors d'une modification effective du monde, dans la même transaction. Les lectures, rejets, actions sans effet et retransmissions ne l'augmentent pas.

`Runtime(path)` crée un monde `fixture` lorsqu'il n'existe pas ; `Runtime(path, data_origin="session")` crée explicitement une session vide. Rouvrir une base conserve son origine ; une origine explicitement différente est refusée. `require_session()` refuse les données `fixture` et `legacy`. Les commandes logiques et plans de démonstration refusent les mondes `session`, qui attendent le contrôleur du corps.

## Migration explicite

Ouvrir une ancienne base v1 ne la modifie pas. Pour la migrer, choisir une sauvegarde qui n'existe pas :

```sh
uv run promethee --data-dir .local/ancien-monde migrate --backup .local/sauvegardes/avant-v2.sqlite3
```

La sauvegarde SQLite est copiée et vérifiée pendant que les écritures sont exclues, avant la migration transactionnelle. Les données sans origine deviennent `legacy`, leur révision commence à zéro ; leur ID de monde, historique et plans sont préservés. Une nouvelle migration d'une base déjà à jour ne fait rien. Une sauvegarde existante n'est jamais écrasée et une version inconnue reste refusée.

Les anciens plans restent exécutables dans les bases `legacy`. Ils ne deviennent pas pour autant des expériences d'agent : créer une base `session` distincte pour le futur agent.

Les noms d'objets identifient des instances ; les noms d'assets identifient des capacités du catalogue. Un `world_id` unique évite de mélanger les journaux de deux mondes exportés dans le même coffre.
