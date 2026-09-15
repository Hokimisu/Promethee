# Contacts des chaussures VRM

Les contrôles Core ne valident pas les appuis de l'apparence pixiv. Deux
déplacements et une posture dont le maillage Core touche le sol sur 120 images
sur 120 ne présentent aucun contact de chaussure VRM sur ces mêmes images.
La correction des appuis visibles reste à réaliser.

Le lecteur expose maintenant les mesures séparées des pieds gauche et droit
dans « Mesures du rendu ». `foot-geometry.js` sélectionne les sommets dont plus
de la moitié des poids de skinning proviennent du pied brut ou de ses
descendants, puis mesure leur position déformée dans le monde. Il n'utilise pas
les indices des os normalisés d'animation pour indexer le maillage. L'asset
pixiv épinglé fournit 493 sommets par pied.

Un contact géométrique utilise la même tolérance symétrique de 0,1 mm que Core.
Une chaussure à 2 mm au-dessus ou à 1 cm sous le sol n'est pas comptée comme
contact. La présence d'un sommet au sol n'atteste aucune force ni équilibre.

| Séquence réelle | Minimum gauche sur la séquence | Minimum droit sur la séquence | Images avec au moins un contact VRM |
|---|---:|---:|---:|
| Série 15, premier déplacement | 10,79 mm | 3,26 mm | 0 / 120 |
| Série 16, retour | 2,98 mm | 11,33 mm | 0 / 120 |
| Série 13, bras levés | 17,01 mm | 20,88 mm | 0 / 120 |
| Pose restaurée de la session objets 07 | 17,29 mm | 20,82 mm | 0 / 1 |

Les minima sont ceux de chaque pied sur toute la séquence, pas une hauteur
constante ni une vitesse de glissement. Les hanches VRM suivent les hanches
Core avec une erreur inférieure à 4 × 10⁻¹⁶ m ; leur déplacement n'explique
donc pas l'écart. L'échelle uniforme reste 1,05102644033269.

Dans la pose restaurée, chaque jambe VRM mesure 0,80769 m. Abaisser uniquement
les chevilles de la hauteur mesurée des chaussures demanderait respectivement
0,82458 et 0,82806 m de portée, bassin inchangé. Une simple résolution des
jambes ne peut donc pas mettre les deux pieds au sol dans cette pose sans
modifier les proportions ou la position du bassin. Abaisser le bassin affecte
à son tour les épaules et la portée des mains : cela doit être traité avec
les objets tenus et vérifié avant d'introduire une correction dans le rendu.
Aucun étirement de membre ni correction verticale n'est ajouté ici.

Les mesures et documents source restent dans `.local/vrm-foot-calibration-01`,
et la pose restaurée dans `.local/vrm-feet-live-01.json`. Ces données sont des
qualifications, exclues de la mémoire personnelle.

## Reproduire sans GPU

Le script emploie les mêmes versions verrouillées de Three.js et three-vrm,
le même retargeting et les mêmes contraintes VRM. Il omet le chargement des
textures, qui ne change pas les positions des sommets. Le hash de l'asset et
le profil des bras sont vérifiés avant la mesure.

Après avoir lancé une lecture avec la commande de [rendu VRM](avatar-rendering.md),
enregistrer son document `/motion.json` dans un fichier local, puis lancer :

```sh
node web/avatar/measure-feet.mjs .local/assets/pixiv-vrm/VRM1_Constraint_Twist_Sample.vrm motion.json nouveau-rapport.json
```

Le rapport conserve les empreintes de l'asset et du document, l'échelle,
l'erreur des hanches, les hauteurs et le nombre d'images en contact par pied.
Un rapport existant n'est pas écrasé. Le script ne lit ni ne modifie SQLite.
Le bouton du lecteur refait la mesure sur le maillage chargé avec ses textures.
Sur les 120 poses du premier trajet de la série 15, cette mesure dans le
navigateur restitue exactement les mêmes hauteurs, nombres de sommets et
comptes de contact que le rapport sans textures. La lecture revient ensuite
à sa pose initiale et ses contrôles redeviennent disponibles. Les sept tests
web, le formatage et la construction du rendu passent.
