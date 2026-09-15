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

Le contrôleur expose création, prise et dépôt cinématiques lorsque l'option
`--object-interactions` est activée. Les points de prise sont les extrémités
externes des ellipsoïdes des bras, à `[±0.082, -0.015, 0]` dans le repère objet.
La main rejoint ce point avec un proxy décalé de 4,5 cm du poignet ; le contrôleur
mesure un résidu inférieur à 1 mm avant l'attachement et une levée de 6 cm.
Les collisions utilisent l'enveloppe globale des ellipsoïdes face à d'autres
objets et aux segments du corps. Ce contrôle conservateur exclut doigts et peau.
Aucune fermeture des doigts, prise physique ou déformation du tissu n'est
qualifiée. Les objets libres restent fixes, sans gravité. Voir le
[parcours mesuré et ses limites](../spatial-objects.md).

L'objet n'est pas créé au lancement d'une session. Son rôle dans les essais ne
définit aucune préférence ou activité attendue de l'agent.
