# Observations d'objets en 3D

Le schéma 9 ajoute un champ optionnel `spatial` aux objets observés. Il permet
de persister une pose et un attachement rigide à la main avec la pose du corps
et les événements d'exécution, dans la même transaction. Le contrôleur propose
maintenant un mode expérimental de création, prise et dépôt cinématiques avec
`--object-interactions`. Il ne simule ni gravité ni articulation des doigts.

## Coordonnées et attachement

`spatial` contient exactement `position`, `rotation` et `attachment`. La position
est un vecteur XYZ en mètres, Y vertical, avec des coordonnées finies entre
−5 et 5. La rotation est une matrice globale 3 × 3, active, à vecteurs colonnes ;
réflexions et matrices non orthonormales sont refusées. Le champ historique
`position` de l'objet reste sa projection XZ, contrôlée à un micromètre près.

Un objet libre a `attachment: null`. Un objet tenu déclare un attachement avec
`joint` (`RightHand` ou `LeftHand` du squelette Core), `position` et `rotation`
locales par rapport à cette articulation. Chaque coordonnée du décalage local
est bornée à 50 cm ; cette borne technique n'est pas une portée anatomique.
Le contrôleur doit établir ce décalage à partir du contact réellement obtenu.
Ces utilitaires ne choisissent pas un attachement et ne prétendent pas qu'il y
a contact parce qu'un décalage est représentable.

La position mondiale est `main.position + main.rotation × décalage_local` et
la rotation mondiale `main.rotation × rotation_locale`. La validation refuse
une position décalée de plus de 0,01 mm ou une différence de coefficient de
rotation supérieure à 0,00001 par rapport à ce résultat. Un attachement exige
une pose articulée valide et la référence `avatar.holding` correspondante.
Un deuxième objet attaché, une référence absente ou un objet déclaré tenu sans
attachement sont refusés. La position de l'objet tenu n'est plus assimilée à
la projection au sol du bassin.

`spatial.follow_attachment` retourne une nouvelle observation d'objet à partir
de la pose courante et de son attachement établi. Il conserve l'entrée et ne
modifie pas SQLite. Le contrôleur fournit ensuite l'observation complète au
service d'exécution. La commande, la parole et l'intention restent insuffisantes
pour constater une prise ou un déplacement.

## Persistance et vérification

La migration explicite 8 → 9 sauvegarde la base et ne change que son numéro de
schéma. Aucun ancien objet logique ne reçoit une hauteur, une orientation ou
une prise inventée. Arrêter les processus qui utilisent une base avant sa
migration. Les nouveaux champs restent absents tant qu'un contrôleur ne les
observe pas. Les actions instantanées du prototype refusent les mondes qui
contiennent des objets spatiaux, même après le départ du contrôleur.

Les tests CPU vérifient un décalage tourné avec la main, la conservation de
l'entrée, le détachement sans changement de pose, les observations incohérentes
et la migration avec sauvegarde et rollback. Ils transmettent aussi une
progression au service d'exécution, puis simulent annulation ou perte du
contrôleur : la dernière pose de corps et d'objet survit à la réouverture,
une observation incohérente ne modifie ni monde ni événement, et une ancienne
réponse ne peut pas remplacer la pose réconciliée. Les identifiants rejoués ne
redéclenchent pas le mouvement.

Ces tests utilisent des poses artificielles pour isoler le contrat de stockage.
Ils ne sont pas une qualification motrice. Le parcours du contrôleur et ses
limites sont décrits ci-dessous. Le [ticket T08](implementation-plan.md) reste ouvert.

## Actions cinématiques expérimentales

Ajouter `--object-interactions` à la commande `promethee run` configurée pour
ARDY. Les commandes apparaissent dans le dossier « Objets » du visualiseur Core
et dans les capacités MCP du même contrôleur. Aucun objet n'est créé au démarrage.
`spawn` et `place` prennent une position **XYZ en mètres, Y vertical** ; `move`
conserve sa cible au sol XZ. Les assets `plush` et `ball` disposent chacun de
points de contact définis sur leur propre géométrie. Le choix « Modèle » du
visualiseur permet de créer un doudou ou une balle.

`take` évalue les deux bras, retient l'approche accessible la plus courte et
prépare toute la trajectoire avant de la jouer. La main rejoint un point de la
surface de l'objet en trois secondes ; l'attachement est établi à cet
instant, puis l'objet est levé de six centimètres en 1,5 seconde. Le point de
main est un proxy situé à 4,5 cm du poignet, pas un contact de peau validé.
`place` conduit l'objet à sa cible en trois secondes et détache seulement à
l'arrivée. Les objets libres restent fixes dans le monde, y compris en hauteur.

La préparation refuse les intersections entre enveloppes d'objets, avec le sol,
les limites de la pièce et des capsules du torse, de la tête, des jambes et des
bras Core. Ces enveloppes conservatrices ne représentent ni les doigts ni la
peau du VRM ; elles ne vérifient pas les limites articulaires ou les collisions
du corps avec lui-même. Les trajectoires ARDY ultérieures vérifient aussi la
distance aux objets avant lecture et transportent l'objet attaché avec la main.
La marche avec un objet tenu n'est pas encore qualifiée.

Une annulation avant contact laisse l'objet libre ; après contact, il reste
tenu à la dernière pose observée. Une cible déplacée pendant l'approche fait
échouer l'action sans écraser son nouvel état. La reprise conserve pose et
attachement et ne rejoue pas l'action terminée.

## Premier parcours sur une pose Core enregistrée

Le script [qualify_object_controller.py](../experiments/motion/qualify_object_controller.py)
exécute le vrai contrôleur et le service SQLite à partir d'une pose Core archivée,
sans nouvelle génération ARDY ni appel au cerveau. Exemple reproductible avec
les artefacts locaux disponibles :

```sh
python experiments/motion/qualify_object_controller.py --motion .local/arm-reach-qualification-02/reach-00.npz --skeleton .local/runtime-holdout-09/motions/conventions.json --output .local/object-controller-qualification-02
```

Le premier essai `object-controller-qualification-01` réussit création, prise,
dépôt et dépôt après redémarrage ; il refuse une seconde prise mains occupées,
une création dans le sol et une cible absente. Les deux annulations conservent
l'état attendu avant/après contact. Le replay contient 280 poses, échantillonnées
nominalement à 20 Hz en omettant les délais de préparation CPU. Dans le VRM pixiv,
l'écart maximal entre la main droite adaptée et la main Core est de 0,000000033 m.
Les pieds visibles restent environ 17 mm au-dessus du sol : cet essai ne valide
pas l'appui. Les doigts restent ouverts. Il reste à partager les contraintes
de portée du VRM avec le contrôleur
avant de déclarer T08 terminé.

Trois essais supplémentaires utilisent le même code moteur, sans retoucher les
seuils après le premier parcours :

| Dossier local | Position initiale avant transformation | Rotation du corps | Décalage XZ | Main utilisée | Parcours |
| --- | --- | --- | --- | --- | --- |
| `object-controller-qualification-02` | `[-0.15, 1.18, 0.27]` | 0° | `[0, 0]` | gauche | 9 résultats attendus |
| `object-controller-qualification-03` | `[0.15, 1.18, 0.27]` | 0° | `[0, 0]` | gauche | 9 résultats attendus |
| `object-controller-qualification-04` | `[0, 1.15, 0.25]` | 90° | `[1, -1]` | droite | 9 résultats attendus |

Les options `--object-position X Y Z`, `--heading-degrees` et `--offset-xz X Z`
reproduisent ces variations. La rotation et la translation s'appliquent au corps
et aux positions cibles ; le doudou apparaît avec une orientation mondiale
identité, donc son orientation relative au corps varie dans le dernier cas.
Les empreintes des sources et de la pose sont conservées dans chaque rapport.
Les essais 03 et suivants sauvegardent aussi la configuration avant exécution,
pour pouvoir reproduire un échec.

Les prises complètes durent 4,71 à 4,85 secondes, préparation CPU comprise ; les
dépôts 3,15 à 3,21 secondes. Les trois séquences passent la vérification de portée
du visualiseur VRM sur toutes leurs poses. Leur inspection à la pose 80 montre
le doudou levé auprès de la main ; les doigts ouverts et l'absence de simulation
physique restent inchangés. Ces variantes ne couvrent pas toute la pièce ni
toutes les postures et ne transforment pas une capacité expérimentale en prise
physique générale.

La [balle géométrique](assets/geometric-ball.md) ajoute une seconde surface de
prise, distincte des onze ellipsoïdes du doudou. Les essais suivants utilisent
`--asset ball`, sans changer les seuils de contact ou de collision :

| Dossier local | Position avant transformation | Rotation du corps | Décalage XZ | Parcours |
| --- | --- | --- | --- | --- |
| `object-controller-qualification-05` | `[0, 1.15, 0.25]` | 0° | `[0, 0]` | 9 résultats attendus |
| `object-controller-qualification-06` | `[0.15, 1.2, 0.28]` | −90° | `[-1, 1]` | 9 résultats attendus |

Les prises durent 4,70 et 4,84 secondes, préparation comprise ; les dépôts
3,15 à 3,19 secondes. Les tests CPU vérifient que tous les points de contact
déclarés sont sur une surface visible, que les deux géométries conservent leur
attachement après annulation et reprise, et qu'une balle ne peut pas être créée
dans l'enveloppe d'un doudou existant. Ni rebond ni lancer ne sont implémentés.
Les deux replays de balle passent le contrôle de portée VRM sur leurs 279 poses ;
la pose 80 a été inspectée visuellement dans chaque cas. Le choix « Balle » puis
« Créer l'objet » a aussi produit une sphère dans la session Core restaurée,
avec un résultat `completed` et un deuxième objet conservé dans le monde.
