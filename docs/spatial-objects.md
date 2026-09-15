# Observations d'objets en 3D

Le schéma 9 ajoute un champ optionnel `spatial` aux objets observés. Il permet
de persister une pose et un attachement rigide à la main avec la pose du corps
et les événements d'exécution, dans la même transaction. Le pilote ARDY actuel
ne propose toujours pas de prise : ce contrat prépare son raccord et ne valide
ni contact, ni collision, ni articulation des doigts.

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
Ils ne sont pas une qualification motrice. La [lecture VRM](avatar-rendering.md)
affiche maintenant un premier doudou déjà attaché, avec adaptation du bras
visible et refus des cibles hors de portée. Restent à raccorder au contrôleur :
approche et contact, attachement au bon instant, collisions, dépôt et essais
sur plusieurs positions et géométries. Le [ticket T08](implementation-plan.md)
reste ouvert.
