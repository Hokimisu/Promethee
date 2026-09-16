# Hermes : format des actions et volume des lectures

Recherche et qualification du 16 septembre 2026, dans la suite des audits
[cycle de vie](12-hermes-lifecycle.md) et
[contexte et outils](13-hermes-context-tools.md).

## Problème observé

Une demande de posture dans la scène réelle a pris 22,515 s avant la réponse.
Le premier appel plaçait `name` dans `action` au lieu de `action.args`.
Le deuxième corrigeait la forme, mais conservait une révision devenue périmée
entre-temps. Après relecture, le troisième était accepté puis exécuté.
Le runtime avait correctement refusé les deux premiers ; Hermes réalisait
lui-même les corrections. Une réponse plus rapide ne doit pas contourner ces
gardes ou transformer une acceptation en réussite.

Les outils de lecture transmettaient également les matrices articulaires et
l'apparence complètes, même pour décider d'une posture ou consulter son statut.
Leur contenu visible pouvait dépasser 20 000 caractères. Ce volume n'était
pas une duplication de `content` et `structuredContent` : le handler Hermes
privilégie le contenu textuel et utilise la structure en repli.

## Changement livré

- Le schéma de `submit_action` décrit l'objet `{kind, args}`, ses deux champs
  obligatoires, les types d'action et un exemple imbriqué. Le dictionnaire
  reçu est toujours validé et enregistré par le runtime, sans réparation.
- Les deux lectures MCP acceptent `detail="summary"` par défaut, ou `"full"`.
  La synthèse omet seulement les grands champs `pose` et `appearance`, au
  niveau du monde ou de l'observation du reçu. Chaque omission est explicite.
  Toutes les autres informations sont conservées depuis une seule lecture.
- La lecture Python reste complète par défaut. Le stockage, le rendu et les
  anciens historiques restent intacts. Le changement de schéma exige de
  recréer l'agent résident, comme les autres évolutions des outils.

Le SDK MCP testé est **2.0.0**, avec Pydantic **2.13.5**. L'annotation
[`WithJsonSchema`](https://pydantic.dev/docs/validation/latest/concepts/json_schema/#withjsonschema-annotation)
personnalise la description ; le type Python reste `dict`. Le transport
Responses natif conserve `strict=False` : ce schéma guide la génération,
il n'en garantit pas la conformité.

La revue croisée a également trouvé une interaction native : déclarer
`args` comme un objet typé déclenchait dans Hermes la conversion d'une chaîne
JSON en dictionnaire avant MCP. Son type est donc décrit en texte et illustré
par l'exemple, sans activer cette nouvelle coercition imbriquée. Le runtime
continue de refuser une chaîne à cet emplacement. La coercition historique
des arguments d'outils par Hermes n'est pas modifiée globalement.

## Vérifications de contrat

34 tests de projection couvrent états confirmés ou non, objets attachés,
initiative, interruption de parole et tous les états d'exécution. Les données
conservées sont comparées au même instantané complet, avec contrôle de l'absence
de mutation et de partage d'objets mutables.

11 tests stdio couvrent les nouvelles lectures, le transport existant et les
gardes de commande. Les formes d'action incorrectes restent des refus
durables `invalid_action`, conservant leurs valeurs et leur idempotence.
Une action correctement imbriquée est acceptée. La conversion native des
schémas par Hermes **2179a279** a été exécutée sans démarrer de modèle :
les contraintes descriptives survivent jusqu'à ses outils.
Le vrai `coerce_tool_args` reproduit également la conversion avec le premier
schéma essayé, puis conserve la chaîne avec le schéma corrigé ; cette chaîne
est ensuite refusée durablement via stdio. Ce contrôle ne démarre pas d'agent
et ne remplace pas une qualification de génération par le modèle.

Sur quatre réponses réelles archivées, la projection effective donne les tailles
ci-dessous à sérialisation JSON identique. Ce sont des **octets UTF-8 du corps
JSON**, pas des tokens ni encore les réponses enveloppées par Hermes.

| Réponse | Complète | Synthétique |
| --- | ---: | ---: |
| Première lecture du monde | 17 203 | 883 |
| Deuxième lecture du monde | 17 664 | 1 357 |
| Troisième lecture du monde | 18 072 | 1 775 |
| Lecture d'exécution | 18 945 | 1 056 |

La diminution de volume atteint environ 90–95 % sur ces observations. Elle ne
prouve pas une baisse proportionnelle du temps de réponse ou du coût.

## Qualification native

Une première campagne de huit tours est **invalide comme comparaison A/B** :
l'environnement filtré du client MCP faisait charger le checkout modifié dans
les deux conditions, malgré les imports directs correctement isolés. Les
schémas réellement reçus par Hermes ont permis de détecter le défaut. Ces
mesures ne servent donc pas à annoncer une amélioration.

Elles restent huit échanges natifs avec les nouveaux outils, de 7,84 à 13,01 s,
sur quatre mondes neufs à contrôleur CPU simulé. Chaque monde enregistre une
seule acceptation et aucune exécution inventée. Deux relectures demandent
explicitement `full`, remontant à environ 20 000 octets de résultats visibles :
le défaut synthétique ne garantit pas que le modèle le choisisse toujours.
Une réponse interprète la pose numérique comme des bras relevés ; cette
interprétation n'est pas une preuve de mouvement dans cet essai sans moteur.

Le harnais corrigé impose la source dans le véritable enfant MCP, journalise
son chemin et son empreinte, puis vérifie le schéma natif avant toute
inférence. La comparaison exploratoire prévue conserve Hermes **2179a279**,
Luna `low`, la persona, les demandes et une observation corporelle identiques.
Elle compare le lot schéma + projection au commit
`dec61b8147a8094105e9479064ad86f4889ce515`. Préparation initiale et tours
résidents sont mesurés séparément. Aucun audio ni mouvement n'est généré.

Le contrôle natif sans inférence a confirmé deux schémas distincts : 3 379
octets pour A, 4 539 pour B. La paire corrigée comporte ensuite **quatre tours
réels**, deux par condition, dans l'ordre A puis B, sans relance après résultat.

| Condition et tour | Réponse utile | Boucle native | Reconnexion MCP | Appels modèle rapportés | Outils | Octets des résultats visibles |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A, première activation prête | 23,885 s | 23,735 s | 0,015 s | 6 | 5 | 40 878 |
| B, première activation prête | 12,535 s | 12,389 s | 0,016 s | 3 | 2 | 2 511 |
| A, second tour résident | 9,713 s | 7,848 s | 1,709 s | 2 | 2 | 20 645 |
| B, second tour résident | 16,525 s | 14,680 s | 1,701 s | 2 | 2 | 20 093 |

La préparation avant le premier message prend 7,79 s en A et 7,90 s en B,
hors colonne « réponse utile ». Le même processus et le même agent servent
les deux tours d'une condition ; MCP est renouvelé avec le nouvel identifiant.
Le contrôleur CPU renouvelle son bail mais ne joue aucune animation.

En A, le modèle reproduit le mauvais format `action.name`, reçoit un refus,
relit le monde et soumet correctement avec un nouvel ID. En B, la première
commande est correctement imbriquée dès son émission. Une seule action est
acceptée par condition, la pose reste inchangée, et les quatre réponses
distinguent la demande acceptée d'un geste exécuté. Pour sa deuxième réponse,
B demande néanmoins `full` aux deux outils : le contexte redevient volumineux.

**Conclusion bornée :** le nouveau schéma évite une correction dans cette paire
et la première réponse arrive 11,35 s plus tôt. La relecture est en revanche
6,81 s plus lente. Une paire exploratoire ne démontre donc ni gain général,
ni latence vocale satisfaisante. Le nombre de requêtes modèle, le choix de la
vue complète et la reconnexion d'environ 1,7 s restent des pistes mesurées.
Les compteurs natifs d'usage sont archivés sans les transformer en facture.

Archives locales : `hermes-tools-ab` (comparaison invalide conservée) et
`hermes-tools-ab-corrected-02` (préparation native et paire corrigée), sous
`.local/`. La copie B fixe `mcp_server.py` à l'empreinte SHA-256
`2802c7d05b645de8c331062cf2c1c2489dd9854b74b11468bf4822eee3fbf013`.

## Sources primaires

- [Outils Promethee](../../src/promethee/mcp_server.py) et
  [projection sans accès au stockage](../../src/promethee/tool_views.py).
- [Conversion des schémas Hermes](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/tools/mcp_tool_schema.py).
- [Résultats MCP visibles](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/tools/mcp_tool_handlers.py).
- [Adaptateur Responses natif](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/codex_responses_adapter.py).
- [Coercition native des arguments](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/tools/arg_coercion.py).

Les conversations, poses et mesures détaillées restent dans les archives
locales de qualification ; aucune mémoire personnelle n'est publiée.
