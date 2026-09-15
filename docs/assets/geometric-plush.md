# Doudou géométrique Promethee

Asset `plush` de la première lecture d'objets en 3D. Sa géométrie originale est
décrite dans [object_models.py](../../src/promethee/object_models.py) et construite
par [objects.js](../../web/avatar/objects.js) : onze ellipsoïdes pour le corps,
la tête, les oreilles, les membres et le visage. Aucun fichier externe, texture,
poids de modèle ou marque n'est utilisé. Le code et cette géométrie sont fournis
sous la [licence MIT du dépôt](../../LICENSE).

Les dimensions sont en mètres, Y vertical, visage vers +Z. L'enveloppe des
primitives mesure 16,4 cm en X, 22,4 cm en Y et 10 cm en Z. L'origine est le
repère local de l'objet, pas son point le plus bas. Le rendu utilise des sphères
de rayon 0,5 mises à l'échelle aux dimensions complètes indiquées dans le fichier.

Capacité vérifiée : affichage d'une pose rigide enregistrée, libre ou déjà
attachée à une main. La présence du modèle ne rend pas `take` ou `place`
disponibles dans le pilote ARDY. Aucune fermeture des doigts, prise physique,
déformation du tissu ou collision n'est qualifiée. Le décalage d'attachement
des essais est un paramètre de vérification, pas un point de prise validé.

L'objet n'est pas créé au lancement d'une session. Son rôle dans les essais ne
définit aucune préférence ou activité attendue de l'agent.
