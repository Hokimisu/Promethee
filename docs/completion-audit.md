# Audit des critères encore ouverts

Audit du 15 septembre 2026, sur le code `f15c577`. Il complète le
[registre](progress.md) sans modifier les critères du [plan](implementation-plan.md).
Les archives ci-dessous sont des qualifications locales, pas des souvenirs
de session. Une réussite ancienne n'atteste pas automatiquement le raccord actuel.

## Mise à jour du 16 septembre 2026

Le choix vocal utilisateur s'est porté sur VoxCPM2 optimisé, puis Luna pour
le dialogue. La [qualification locale](research/11-short-dialogue.md) vérifie
maintenant de vraies sorties vocales et leurs reçus de lecture dans le navigateur,
avec ARDY actif. Elle ne ferme pas T11 : entrée microphone, interruption
acoustique aux différentes étapes et coût réel restent ouverts. Les sources de
la [scène expérimentale](../experiments/voice/realtime/README.md), leur configuration,
leurs tests et les versions de l'environnement vocal sont désormais livrés ;
les dépendances vocales ont été réinstallées dans un environnement neuf.

Le préchauffage Hermes, le contrat système séparé et la mesure des phases sont
implémentés dans le socle. Six tours réels montrent des réponses de 3,50 à
26,35 s ; aucune fluidité continue n'est revendiquée. Le profil vocal approuvé
est conservé. Les 577 tests réussis de cette étape et les deux tests ignorés couvrent les
contrats du code, pas les critères audio matériels manquants. T12 conserve sa
dépendance vocale ; aucun nouveau succès T07–T08 n'est déduit de la gestuelle
de présence de cet essai. Le mode résident ajouté ensuite réutilise effectivement
Hermes et renouvelle MCP par tour ; ses trois appels natifs et leurs limites
figurent dans le [rapport de recherche](research/12-hermes-lifecycle.md).

La [révision de commande](command-revision.md) corrige désormais le conflit
causé par les observations de présence entre `read_world` et `submit_action`.
La révision stricte reste disponible ; une seule garde est admise par demande,
sans remplacement silencieux de celle choisie. Les tests du vrai transport MCP
couvrent les types stricts, les gardes absentes ou concurrentes, le rejeu et le
refus d'un ancien tour.

L'essai `command-revision-real-01` confirme ce raccord sur une vraie présence
ARDY et une posture demandée par Luna résident, dans Hermes 0.21.3 G `2179a279`.
Entre la dernière lecture `203/3` et l'admission `247/3`, 44 poses distinctes
sont archivées ; la posture termine 7,928 s après admission. Une première
demande mal formée est refusée, puis corrigée par la boucle native avec un
nouvel ID : une seule action acceptée, aucun rejeu automatique de l'hôte. Le
second tour consulte réellement `read_world` et `read_execution`. Les durées
natives de 18,82 et 8,02 s ne sont pas une garantie de fluidité. L'essai ne
comporte ni voix ni navigateur. Vérification actuelle : 647 tests du socle
réussis, 2 ignorés ; 124 tests de scène et 7 sous-tests réussis.

La tolérance de marche v5 doit encore subir une nouvelle série indépendante
après fixation de ses critères. Ni cette posture, ni le mode résident, ni la
publication de la scène ne ferment cette qualification. Marcher avec un objet
tenu reste distinct des essais de prise et dépôt ; microphone, coût réel et
budget persistant raccordé à la scène vocale restent également ouverts.

Le reste du document conserve les preuves de l'audit du 15 septembre.

## T07 — Corps et résultat observé

| Exigence | Preuve inspectée | Conclusion |
|---|---|---|
| Soumission distincte de la progression et de la fin | `tests/test_kinematic.py` : intention sans téléportation, observation persistée, posture échouée ; registre réel `astra-body-qualification-02/executions.json` | Couvert en tests ; essai réel avec une posture terminée et une annulée |
| Monde, historique et poses décrivent la même exécution | Les deux exécutions terminales de cet essai figurent exactement dans `execution_events.json`. Leurs observations figurent dans les 2 038 observations capturées. La dernière observation est exactement celle de l'annulation | Concordance des données vérifiée ; la revue visuelle antérieure est décrite dans le [guide Hermes](hermes-setup.md) |
| Déplacements et postures variés, calibration séparée | `runtime-transition-holdout-01/criteria.json` et `results.json`, graine 118123 ; [calibration et nouvel essai](live-avatar.md#continuité-des-appuis-entre-mouvements) | Deux postures et un déplacement terminés ; premier déplacement refusé, sans succès inventé |
| Mesures à la cible et latence | Même essai : postures 10,228 et 10,349 s ; déplacement 13,138 s, erreur 8,92 mm | Ces valeurs incluent la préparation ; elles ne décrivent pas toutes les requêtes possibles |
| Contacts et continuité du VRM | Trois préparations acceptées : 120 contacts de surface sur 120 poses, raccord initial inférieur à 0,02 mm ; limite de correction du bassin conservée à 5 cm | Mesures géométriques, sans force, équilibre ni garantie de collision entre les jambes |
| Arrêt à différents moments | Tests avant envoi, pendant génération et lecture ; essai réel Astra annulé à l'image 10, registre `cancelled`, pose finale conservée | L'arrêt n'est pas une confirmation de la posture demandée |
| Perte du contrôleur et reprise | Ancien parcours Core : `manual-session-01/crash-measurement.json` et `restart-measurement.json`. Parcours préparé : `prepared-crash-qualification-04`, processus tué à l'image 10, bail expiré, reprise par le contrôleur courant | Corps non confirmé après perte, puis checkpoint exactement restauré ; ancienne action interrompue, aucun rejeu. Rendu avant/après inspecté |
| Session explicite, commandes manuelles et données exclues | `python -m promethee.run --help`, `run.py`, tests HTTP et de checkpoints ; [commande et reprise](live-avatar.md) | Implémenté ; tests distinguent demande d'arrêt et retour du corps |

La vérification supplémentaire du parcours préparé est décrite dans la
[qualification de panne](live-avatar.md#panne-du-contrôleur-et-reprise-du-vrm-préparé).
Elle ferme le manque de preuve identifié pour T07 dans cet audit.
Un refus géométrique documenté n'impose pas à lui seul une nouvelle boucle
d'optimisation : le plan exige un résultat fidèle et des limites mesurées,
pas un taux d'acceptation de 100 % pour ARDY.

## T11 — Voix

Le [raccord Live](live-integration.md) utilise le vrai SDK isolé et le même
hôte Hermes. Le serveur vocal et les périphériques des tests sont simulés.
Les 419 tests du commit audité ne prouvent donc aucune conversation audio réelle.

Restent requis :

- Accès effectif au fournisseur vocal avec le compte cible.
- Interruption acoustique pendant écoute, raisonnement, parole et mouvement,
  sans reprise d'une ancienne sortie distante. Vider le buffer à réception
  d'une transcription ne prouve pas ce comportement.
- Qualification réelle de la continuité vocale : les fragments non délégués
  sont maintenant persistés dans le même registre Hermes ; redémarrage,
  doublons et arrivées pendant un raisonnement sont couverts par tests.
- Mesures de réponse utile, coupure et coût d'une session réelle, avec
  distinction entre intention, mouvement en cours et résultat confirmé.

## T10, T12 et T13

Les rapports `astra-memory-qualification-02/report.json` et
`astra-initiative-qualification-02/report.json` confirment des essais avec
`gpt-6-astra`, pas seulement des doublons. Le premier conserve deux notes
sourcées dans un monde et aucune dans l'autre, sans action. Le second conserve
les budgets épuisés, la pause après redémarrage, le retrait des capacités et
aucune action ; aucune initiative personnelle n'est activée.

Ces preuves sont détaillées dans les contrats [mémoire](memory.md) et
[initiative](initiative.md). Elles ne ferment pas la dépendance vocale de T12.
T13 reste conditionnel : aucun entraînement complet ni connecteur supplémentaire
ne découle de cet audit. Une extension exige une limite mesurée et son périmètre.
