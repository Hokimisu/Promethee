# Commander pendant les gestes de présence

Le service refusait une commande lorsque les gestes de présence avaient changé
la pose entre `read_world` et `submit_action`. La révision stricte protégeait
bien le snapshot, mais pouvait périmer plusieurs dizaines de fois pendant un
seul appel au modèle. Arrêter ces gestes pendant toute sa réflexion masquait
le conflit en immobilisant le personnage.

Le [contrat du schéma 12](contracts.md#exécutions-du-corps) expose maintenant
`command_revision`. Hermes peut demander une action depuis la pose actuelle
sans exiger que l'image lue quelques secondes plus tôt soit restée identique.
La garde stricte `expected_revision` reste disponible. Il faut en choisir une,
et l'identifiant ainsi que l'enveloppe restent identiques lors d'un rejeu.

## Ce qui conserve ou invalide la lecture

`observe_idle` valide toujours l'observation complète avant de la publier.
Seuls les changements de pose, de position du corps, de date et de corrections
animées du même avatar préparé sont exclus de la nouvelle garde. Les objets,
la prise, l'assise, le squelette, l'identité de l'apparence et l'autorité du
contrôleur restent comparés. Une modification puis restauration d'un objet
ne rétablit pas une ancienne garde.

La commande est validée sur l'état courant dans la même transaction que son
admission. La portée logique est donc recalculée ; les contacts et la portée
anatomique restent contrôlés par le pilote. Le tour de conversation doit encore
être valide, le contrôleur disponible et aucune autre action active.
Une admission bloque les publications idle suivantes ; le contrôleur de
présence abandonne alors son futur et reprend le mouvement explicite depuis
l'observation persistée. Aucune pose ni cible réussie n'est inventée.

Le compteur `idle_pose_updates` est sauvegardé avec la pose et `revision`.
`command_revision` est leur différence, calculée à la lecture. La migration
11→12 nécessite une sauvegarde explicite et initialise le compteur à zéro,
sans reclasser les anciennes observations. Arrêter tous les processus utilisant
la base avant migration, puis recréer l'agent résident avec les nouveaux outils.

## Qualification du 16 septembre 2026

Essai dans un monde neuf `qualification`, exclu de la mémoire personnelle,
avec l'agent natif Hermes 0.21.3 (`2179a279…`), Luna en mode résident, ARDY
et le VRM préparé. Deux tours maximum, sans nouvelle tentative automatique
de l'hôte. Les critères ont été écrits avant le démarrage. La voix et le
navigateur ne participaient pas à cet essai.

Hermes a d'abord lu le monde puis mal formé sa demande de posture : `name`
figurait à côté de `kind`, au lieu de figurer dans `args`. Le service l'a
refusée avec `invalid_action`. Hermes a relu le monde et envoyé une nouvelle
enveloppe correcte sous un nouvel identifiant. Cette correction native et son
coût restent dans les traces : il ne s'agit pas d'une réussite au premier appel.

| Mesure | Résultat observé |
|---|---|
| Dernière lecture avant la demande correcte | `revision=203`, `command_revision=3` |
| Monde examiné lors de l'admission | `validated_revision=247`, `validated_command_revision=3` |
| Intervalle entre lecture et admission | 44 poses distinctes observées et archivées ; garde de commande inchangée |
| Actions acceptées | Une posture `arms_raised`, après un rejet de format |
| Résultat du contrôleur | `completed`, 7,93 s après l'admission |
| Premier tour natif | 18,82 s, lectures, rejet, correction et réponse compris |
| Second tour | 8,02 s ; nouveaux appels `read_world` et `read_execution`, puis compte rendu de fin |

Les 44 changements de pose auraient invalidé la garde stricte. La nouvelle
garde a effectivement servi à admettre la demande depuis une observation
plus récente, sans suspendre la présence pendant le raisonnement. Les tests
CPU et MCP stdio vérifient séparément le refus de l'ancienne garde stricte,
les erreurs d'entrée, le rejeu sans effet, les tours périmés, l'indisponibilité
du contrôleur, la portée courante, le rollback et la reprise après redémarrage.
La suite comprend 647 tests réussis et deux ignorés ; la scène expérimentale
conserve 124 tests et sept sous-tests réussis.

Archives locales : `.local/command-revision-real-01/report.json`, `audit.json`,
`execution-events.json` et `observations.jsonl`. Les réponses natives et les
révisions des sources restent dans cette archive ignorée par Git.

Cette qualification ferme le conflit précis pour une posture pendant la
présence. Elle ne garantit ni la fluidité visuelle ni une latence constante.
La marche avec un objet tenu reste distincte : déplacer cet objet change le
monde et invalide encore la garde. Le microphone, l'interruption acoustique
et le budget persistant de la scène vocale restent à qualifier.
