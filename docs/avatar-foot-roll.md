# Appui sur le talon ou la pointe

Le préparateur VRM distingue désormais un appui de toute la semelle, du talon
seul ou de la pointe seule. Cela corrige un blocage observé sur un déplacement
ARDY : la chaussure était entièrement figée lorsque seule sa pointe devait
rester au sol. Le talon ne pouvait pas monter et la correction du bassin
dépassait sa limite.

Ce changement s'applique aux nouvelles poses du mode `--prepare-avatar` de la
[session en direct](live-avatar.md). Il ne modifie ni les poses déjà enregistrées
ni leur format. Les contraintes de hauteur, de continuité, de portée et de
glissement restent inchangées. Il s'agit toujours de cinématique, sans simulation
de force d'appui ou d'équilibre.

## Cause mesurée

Dans le [cas 02 de continuation](research/06-continuous-trial.md), le deuxième
bloc ARDY passe les contrôles du corps Core. À sa pose 15, les contacts sont
`[false, true, false, false]` : pointe gauche seule. L'ancien préparateur traitait
`heel || toe` comme un pied entièrement immobilisé, avec cheville et rotation
fixes. Il exigeait alors **6,670 cm** d'abaissement du bassin, au-delà des 5 cm
autorisés. Le refus ne venait pas de la durée de génération.

La même trajectoire et la même apparence initiale passent après correction :
les 120 poses ont un contact géométrique. L'abaissement maximal mesuré est
**4,317 cm** ; la vitesse maximale mesurée des sommets restant en contact est
0,0667 m/s, sous la limite existante de 0,2 m/s. Le plus grand écart initial
entre deux blocs préparés est de 0,354 mm, sous la limite de 2 cm.

Ce résultat compare les mêmes données. Il ne provient ni d'une nouvelle graine,
ni d'une hausse des tolérances, ni d'une retouche de la vidéo.

## Calcul

Pour un appui partiel, le préparateur choisit un sommet de la surface de la
chaussure près du sol, du côté du talon ou de la pointe indiqué par ARDY. Son
emplacement au sol reste fixe. Les rotations du pied et des orteils continuent
à suivre le mouvement source ; la cible de cheville est recalculée depuis
l'écart entre ce sommet animé et la cheville. La jambe rejoint cette cible
sans changer la longueur de ses os.

Le passage vers un appui complet conserve le point déjà ancré. Le passage vers
une phase sans appui libère l'ancrage. La dernière surface effectivement
préparée sert aux transitions ; l'apparence initiale n'est pas modifiée.
Les erreurs de portée indiquent maintenant la pose et l'abaissement demandé.

L'ancrage d'un sommet ne suffit pas à prouver la qualité du mouvement. Les
mesures du maillage et les contrôles de transition sont donc toujours appliqués
à l'ensemble des poses avant leur lecture.

## Vérifications du 15 septembre 2026

Quatre tests couvrent talon et pointe, à gauche et à droite, dans un repère
tourné et déplacé. Ils vérifient que le point de contact reste fixe, que l'autre
extrémité de la chaussure se soulève, que la cheville bouge, que les longueurs
des jambes restent constantes et que le retour à un appui complet est cohérent.
Les dix tests de rendu précédents passent aussi.

| Essai réel | Résultat | Limite conservée |
|---|---|---|
| Continuation 02, graine 128124, mêmes poses qu'avant correction | Trois blocs VRM préparés ; déplacement vers `(0 ; 1)` m | Séquence hors session ; pas de contrôle continu du runtime |
| Reprise de la série 118123, cibles `(-0,17 ; 0,19)` puis `(0,28 ; -0,07)` | Deux postures et le second déplacement terminés, comme avant | Premier déplacement encore refusé : 5,060 cm de correction demandée à la pose 57 |
| Nouvelle série 138124, cibles `(0 ; 0,75)` puis `(0,35 ; 0,45)` | Deux postures terminées | Premier déplacement refusé par les appuis Core : 115 poses en contact sur 120. Second refusé par la variation de correction VRM supérieure à 15 mm par pose |

Sur la dernière trajectoire, une comparaison avec l'ancien préparateur refuse
également l'export, pour dépassement des 5 cm de hauteur. Le nouveau refus de
transition n'est donc pas la perte d'un succès antérieur. Il reste à résoudre.

Les séries du contrôleur utilisent le vrai processus ARDY, le préparateur VRM,
la lecture à 20 Hz et le registre SQLite. Leurs observations et résultats sont
conservés dans `.local/runtime-foot-roll-replay-01` et
`.local/runtime-foot-roll-holdout-01`. Ces petites séries ne donnent pas un taux
de fiabilité général. Les refus restent des échecs dans le monde, sans
téléportation à la cible.

Une capture réelle du lecteur du cas 02 est conservée dans
`.local/exports/promethee-foot-roll-20260915.webm` : 6,469 s, 1600 × 900,
capture à 30 images/s de poses à 20 Hz. Elle montre le déplacement et l'arrivée ;
les images entre 2 et 5 secondes ont été inspectées. Ce n'est pas une preuve
de synchronisation vocale, de physique ou de naturalité complète.

Les 423 tests Python passent, deux sont ignorés. Les 14 tests JavaScript,
les contrôles de style et les constructions Python et navigateur passent.
Les qualifications et leurs médias restent exclus de la mémoire de l'agent.

## Correction du pivot lors d'une présence, 16 septembre 2026

Un autre refus provenait du choix du sommet servant de pivot. Le sélecteur
cherchait d'abord le bas de toute la chaussure, puis sa pointe parmi ces sommets.
Lors du passage de la semelle à la pointe, entre les poses 32 et 33 d'un segment
archivé, la chaussure inclinée lui faisait choisir un sommet **derrière la
cheville**. L'IK travaillait donc autour du talon pour un contact de pointe.

Le sélecteur limite désormais les candidats à la région demandée : au-delà de
l'articulation des orteils pour la pointe, derrière la cheville pour le talon.
Il applique ensuite la même bande basse de 2 mm. Une région absente est refusée.
Aucun seuil, avatar ou mouvement source n'a été modifié.

| Même segment, pose 33 | Avant | Après |
|---|---|---|
| Variation de correction verticale | 26,172 mm | 10,084 mm, sous la limite de 15 mm |
| Point le plus bas après IK, avant remise au sol | −34,548 mm | −2,510 mm |
| Minimum du pied opposé après remise au sol | +35,460 mm | +1,500 mm |
| Export | Refus | 41 poses validées, origine exacte |

Le rejeu CPU du segment complet passe les gardes géométriques puis le validateur
Python. Un segment voisin et deux autres segments contenant des appuis partiels
ont été rejoués avant et après : leurs métriques restent identiques. Les 18 tests
JavaScript passent ; les trois nouveaux tests échouent avec l'ancien sélecteur.

L'inspection visuelle porte sur les vrais sommets des chaussures, pas sur une
vidéo complète du corps. Le genou gauche se déplace encore de **8,389 cm** à cette
transition ; le correctif ne la lisse pas. Il ne prouve ni naturalité complète,
ni équilibre physique, ni réalisation simultanée de tous les contacts prédits.
Les artefacts de qualification restent locaux et hors de la mémoire de l'agent.

## Essai distinct de posture d'arrivée

`continuous_trial.py --arrival-pose` peut désormais contraindre la dernière
pose à une copie translatée de la pose source. Sur le cas 01, graine 128123,
l'arrivée est plus droite dans le lecteur, avec une erreur de racine de
18,3 mm et les trois blocs préparés. L'historique initial était une posture
debout adaptée à ce test.

Cette option reste **hors du contrôleur de production** : copier une pose de
départ prise au milieu d'un pas ne définit pas un arrêt debout. L'essai ne
résout pas non plus l'attente en début de mouvement. Il motive un travail
distinct sur trajectoire, vitesse et posture d'arrivée, suivi d'une qualification
sur des départs variés. Les données sont conservées dans
`.local/continuous-arrival-trial-01` et `.local/continuous-arrival-appearance-01-roll`.

La suite reste la génération continue avec historique réellement exécuté,
des transitions acceptables et une validation sur des demandes variées.
La voix réelle et l'expérience de caméra manipulée ne sont pas validées par
ce correctif.
