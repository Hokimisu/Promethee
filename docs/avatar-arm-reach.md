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
collision de tout le corps. Le raccord du VRM à une session interactive reste
à livrer ; le rendu VRM actuel relit des observations enregistrées.
