# Portée du bras de l'avatar

Le mode `--object-interactions` de `promethee run` vérifie maintenant la portée
de l'apparence pixiv avant la lecture d'une prise ou d'un dépôt. La vérification
s'applique aussi à la reprise d'un objet tenu et aux trajectoires ARDY qui le
transportent. Une cible accessible au squelette Core peut être impossible pour
l'avatar, dont les segments sont plus courts.

## Profil partagé

[pixiv_arm_profile.json](../src/promethee/pixiv_arm_profile.json) contient les
positions mondiales au repos des articulations du torse et des bras du
[modèle pixiv](assets/pixiv-vrm-sample.md), leur hiérarchie normalisée et leur
correspondance Core. Ces coordonnées dérivent du VRM et restent couvertes par
sa VRM Public License 1.0 ; elles ne sont pas réattribuées sous la licence MIT
du code. L'empreinte du modèle figure dans le profil.

L'échelle uniforme 1,05102644033269 vient du visualiseur qualifié, qui compare
la hauteur des hanches Core au bas du modèle au repos. Le contrôleur refuse
une hauteur de repos Core différente de celle du profil. Le navigateur vérifie
indépendamment l'échelle, les positions au repos, la hiérarchie et les noms des
articulations du modèle chargé avant de lire une animation. Modifier une
apparence exige une nouvelle qualification de son profil.

Le calcul reconstruit la position de l'épaule visible depuis la racine et les
rotations Core du torse. Les deux segments du bras droit mesurent environ
23,1071 et 22,5640 cm après mise à l'échelle, soit 45,6711 cm au total. La main
doit rester dans l'anneau géométrique accessible, avec une marge de 0,01 mm.
La normalisation des petites erreurs d'arrondi des matrices ne change pas la
pose enregistrée. La vérification concerne chaque pose de l'approche, de la
levée ou du dépôt, et pas uniquement la cible finale.

Le planificateur essaie l'autre main si une première approche est incompatible.
Si aucune ne convient, l'action échoue sans démarrer la trajectoire ni attacher
l'objet. Les observations et événements décrivent cet échec ; aucun résultat
souhaité n'est écrit à leur place. Les utilisateurs internes de
`KinematicController` doivent fournir `arm_reach_check` pour sélectionner cette
apparence ; la commande de session et le script de qualification le font.

## Vérification locale

[qualify_avatar_reach.py](../experiments/motion/qualify_avatar_reach.py) relit le
VRM original, compare ses coordonnées au profil, contrôle des observations
enregistrées et exerce le vrai contrôleur et SQLite. Il ne génère pas de
mouvement ARDY et n'appelle aucun cerveau. Tous ses mondes sont des données
de qualification, exclues de la mémoire personnelle.

```sh
python experiments/motion/qualify_avatar_reach.py --avatar .local/assets/pixiv-vrm/VRM1_Constraint_Twist_Sample.vrm --skeleton .local/runtime-holdout-09/motions/conventions.json --source-motion .local/arm-reach-qualification-02/reach-00.npz --unreachable-motion .local/arm-reach-qualification-02/reach-02.npz --replays .local/object-controller-qualification-01/objects.json .local/object-controller-qualification-02/objects.json .local/object-controller-qualification-03/objects.json .local/object-controller-qualification-04/objects.json .local/object-controller-qualification-05/objects.json .local/object-controller-qualification-06/objects.json --output .local/avatar-reach-review
```

L'essai `avatar-reach-qualification-01` trouve un écart nul entre les positions
relues dans le VRM et le profil. Il accepte les 1 676 poses des six parcours
d'objets précédents. Sur l'ancienne cible haute, il refuse les poses 58–60 :
45,7628 à 45,9340 cm demandés pour 45,6711 cm disponibles. Cela retrouve le
refus déjà observé dans le visualiseur.

Un doudou à `[0, 1.45, 0.45]` permet au calcul Core seul de préparer 91 poses.
Avec le profil pixiv, le contrôleur refuse les deux mains, ne démarre aucune
trajectoire et conserve exactement la pose et l'objet. Le parcours complet de
balle `object-controller-qualification-07`, avec contrôle pixiv actif, réussit
les neuf résultats attendus, y compris annulations et dépôt après redémarrage.
Le vrai VRM chargé dans le navigateur accepte aussi le profil partagé.

Cette vérification établit la portée du poignet, pas les limites anatomiques,
la fermeture des doigts, le contact de peau, l'équilibre ou l'absence de
collision de tout le corps. Le raccord à une [session interactive](live-avatar.md)
est livré ; l'adaptation des appuis visibles reste expérimentale.

## Portée après adaptation de hauteur

`PixivArmReach.check(pose, skeleton, hand, root_y_offset=...)` accepte maintenant
un décalage vertical explicite du bassin de l'apparence. Ce paramètre nommé est
exprimé en mètres dans le monde, borné à ±5 cm et nul par défaut. Le calcul
déplace l'épaule reconstruite, mais conserve la pose Core et la cible mondiale
de la main. Les valeurs non finies, booléennes ou hors limites sont refusées.
Le paramètre ne calcule pas et n'active pas une correction des pieds.

Un contre-exemple analytique vérifie la nécessité du contrôle : une cible
45 cm au-dessus de l'épaule est accessible sans décalage, puis inaccessible
après un abaissement de 2 cm, pour un bras de 45,67 cm. La limite de repli
minimal reste elle aussi contrôlée. Ces cas sont des tests géométriques,
pas de nouvelles prises réalisées par l'avatar.

Le [comparateur](../experiments/motion/qualify_offset_reach.py) a ensuite relu les
sept parcours objets réels, soit **1 955 poses**, avec la translation VRM
mesurée image par image par `measure-feet.mjs --settle`. Les empreintes relient
chaque rapport au document de mouvement et à l'asset pixiv. Les deux mains,
les deux géométries, les translations et les orientations des parcours sont
couvertes ; le calcul CPU accepte les mêmes cibles que la résolution du vrai
VRM. Le bassin descend d'environ 17,29 mm et l'erreur maximale de main rendue
reste inférieure à 3,7 × 10⁻⁸ m. Les distances épaule-poignet mesurées vont de
0,22545 à 0,40664 m. Les données et sources restent dans
`.local/avatar-offset-reach-qualification-01`, hors mémoire personnelle.

```sh
python experiments/motion/qualify_offset_reach.py --avatar .local/assets/pixiv-vrm/VRM1_Constraint_Twist_Sample.vrm --replays .local/parcours-objets --output .local/nouvelle-qualification
```

Chaque dossier de parcours contient `motion.npz`, `conventions.json` et
`objects.json`. On peut fournir plusieurs dossiers à `--replays`. Le script
utilise le Node installé et les dépendances verrouillées de `web/avatar` ;
il mesure le skinning réel sans charger les textures et n'ouvre aucun monde.

Les 14 tests de portée et la suite complète de 279 tests passent ; deux tests
de la suite sont ignorés sous Windows. Les appels existants du contrôleur
gardent le décalage nul, correspondant au rendu en direct livré. L'adaptateur
d'appuis devra lui fournir les corrections réellement prévues avant lecture,
puis les transmettre et les conserver avec les poses pour la reprise. Le
paramètre seul ne qualifie donc pas encore les appuis en direct.
