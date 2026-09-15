# Balle géométrique Promethee

Asset `ball` : une sphère bleue de 12 cm de diamètre, centrée sur son origine.
Sa géométrie originale est définie dans
[object_models.py](../../src/promethee/object_models.py), sous la
[licence MIT du dépôt](../../LICENSE). Aucun fichier, marque ou texture externe.
Les deux visualiseurs utilisent la même primitive et les mêmes dimensions.

Les points de contact sont `[-0.06, 0, 0]` et `[0.06, 0, 0]` dans le repère de
l'objet. Ils se situent sur sa surface ; le contrôleur y conduit un proxy de
main, puis attache la balle et la lève de 6 cm. Le dépôt détache seulement à
l'arrivée. Ce mode cinématique ne simule ni doigts, ni gravité, ni roulement,
rebond, lancer ou déformation. Une balle libre conserve sa pose mondiale.

Les essais `object-controller-qualification-05` et `06` utilisent le vrai
contrôleur avec une pose Core archivée. Ils vérifient prise, dépôt, mains
occupées, cible absente, création dans le sol, annulation avant/après contact
et dépôt après redémarrage. Le second varie hauteur, position, orientation du
corps et emplacement dans la pièce. Voir les paramètres et limites dans
[les observations spatiales](../spatial-objects.md).

La balle n'est pas créée au démarrage. Le choix du modèle reste explicite dans
les commandes ou l'interface et ne définit aucune activité attendue de l'agent.
