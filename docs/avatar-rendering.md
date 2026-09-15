# Avatar VRM animé

Une vue Three.js affiche l'[avatar anime pixiv](assets/pixiv-vrm-sample.md) avec
ses textures et les rotations d'un enregistrement ARDY Core. Lecture, pause,
choix d'une pose et superposition du squelette source sont disponibles.
Cette vue ne modifie pas le monde et ne pilote pas encore une session en direct.

## Choix du rendu

Le `GlbHandle` de Viser ne donne pas accès aux os du GLB importé. Son rendu de
maillage articulé propose des couleurs simples, sans les textures et matériaux
du VRM. Ce besoin concret justifie Three.js / three-vrm pour l'apparence demandée.
Viser conserve son rôle de diagnostic du corps Core et de pilotage manuel.
Il ne s'agit pas d'un second moteur de décision ou de physique.

Versions fixées : Three.js **0.186.0**, `@pixiv/three-vrm` **3.5.5**, esbuild
**0.28.2**, Node **24.13.1** lors de l'essai. Les dépendances et leur intégrité
sont verrouillées dans `web/avatar/package-lock.json`. Le code de ces trois
paquets est sous licence MIT ; la licence du personnage reste distincte.
Les mentions des dépendances sont conservées dans `app.js.LEGAL.txt` lors du build.

## Lancer la lecture

Depuis le dépôt, installer et construire les fichiers web :

```sh
npm --prefix web/avatar ci --ignore-scripts
npm --prefix web/avatar run build
uv sync --locked --extra avatar
```

Télécharger le modèle avec la commande de sa fiche de provenance, puis fournir
les fichiers de son propre essai moteur :

```sh
uv run --extra avatar promethee-avatar --web-root web/avatar/dist --avatar .local/assets/pixiv-vrm/VRM1_Constraint_Twist_Sample.vrm --skeleton .local/essai/conventions.json --motion .local/essai/motion.npz --port 2343
```

Ouvrir `http://127.0.0.1:2343/`. Le serveur ne sert que les fichiers déclarés ;
il n'expose ni dossiers, ni SQLite, ni API d'action. Le NPZ est lu sans pickle,
ses rotations sont validées et la durée est limitée à 1200 poses à 20 Hz.
Le VRM doit correspondre à l'empreinte de l'asset dont la licence a été vérifiée.
Les dépendances graphiques ne sont pas nécessaires aux tests du socle Python.

## Correspondance des poses

Le lecteur utilise l'[API humanoïde normalisée de three-vrm](https://pixiv.github.io/three-vrm/docs/classes/three-vrm.VRMHumanoid.html).
Les articulations sont associées par leur nom dans l'export Core, jamais par
les indices bruts des os du VRM. Les matrices Core sont mondiales et agissent
sur des vecteurs colonnes. Pour chaque os cible, la rotation locale est obtenue
en retirant celle de son parent, après composition avec son orientation de repos.
Cela conserve les rotations des articulations intermédiaires du tronc Core
absentes du VRM ; `Spine2` alimente `chest`, `Spine3` alimente `upperChest`.

La mise à l'échelle est uniforme, calculée une fois depuis la hauteur neutre
des hanches au-dessus du point le plus bas. Les hanches rendues sont ensuite
placées à la position Core observée. Aucune translation horizontale de cible,
animation d'attente ou correction verticale par image n'est ajoutée. Les
proportions des membres restent celles de pixiv : les positions des mains et
des pieds peuvent donc différer du corps Core.

Pour une lecture contenant des objets attachés, le bras visible est désormais
adapté à la position Core de la main correspondante par une résolution à deux
segments. Les longueurs du VRM et l'orientation de main sont conservées ;
l'objet garde sa pose mondiale observée. Cette adaptation s'applique à toute
la séquence pour les mains concernées, y compris avant un attachement éventuel.
Toutes les cibles sont vérifiées avant d'activer la lecture. Une cible hors de
portée ou un plan de flexion indéterminé rend la lecture indisponible, sans
étirer les bras ni rapprocher l'objet. Les limites articulaires et collisions
ne sont pas évaluées par ce calcul.

## Lecture d'objets enregistrés

L'option `--objects observations.json` accepte une liste d'observations complètes,
une par pose du NPZ, dans le [contrat spatial](spatial-objects.md). La pose du
corps doit correspondre exactement à la pose du mouvement. Le fichier est
limité à 16 Mio ; chaque objet exige une pose spatiale valide et un modèle
visuel connu. Le [doudou géométrique](assets/geometric-plush.md) est le premier
modèle fourni. Le serveur reste en lecture seule et n'expose aucune action.

Le script [qualify_object_replay.py](../experiments/motion/qualify_object_replay.py)
prépare un essai avec un objet déjà attaché. Il conserve les observations,
les empreintes et le script dans un nouveau dossier local :

```sh
uv run --extra avatar python experiments/motion/qualify_object_replay.py --motion SOURCE.npz --skeleton conventions.json --output .local/object-review --side right
```

Ajouter ensuite `--objects .local/object-review/objects.json` à la commande
du visualiseur. Cet essai ne simule ni approche, ni contact initial, ni dépôt.

Les essais locaux `object-replay-qualification-01` à `03` ont révélé puis
isolé l'écart de proportions. Le premier, cible haute du bras droit, montrait
jusqu'à 16,48 cm entre la main visible et la main Core. L'alignement refuse
cette séquence dès qu'une cible dépasse la portée VRM : 45,8 cm demandés pour
45,7 cm disponibles à la première pose refusée. Le message est visible et
les contrôles de lecture restent désactivés.

Les deux cibles plus proches, à droite et à gauche, passent sur leurs 61 poses.
Après adaptation, la distance maximale de la main concernée à sa position Core
est respectivement 2,71 × 10⁻⁸ m et 2,78 × 10⁻⁸ m. Les vues d'arrivée montrent
le doudou auprès de la main ; les doigts restent ouverts et le doudou bascule
avec elle. La main non concernée conserve son écart de proportions. Les
chaussures restent à environ 1,73 cm du sol : cet essai ne valide pas l'appui.

Les sources NPZ sont respectivement les `reach-02`, `reach-00` et `reach-03`
de `arm-reach-qualification-02`. Les SHA-256 des observations sont
`494ccf0ce88c4a6d82a456f0885667a5609f3c446924c272c0f64eb67295b4f9`,
`1dfca11d94a17dbe81c0b8a2324ca5f7dd2d612eb2050f471195916cfcc7e4eb`
et `c460db25837021dce2f227cc65670b1ad1d5b15edef931c47421979be11b6c09`.
Ces données de qualification restent exclues de la mémoire de l'agent.

## Vérification locale

Le 15 septembre 2026, le navigateur intégré a affiché les textures, la posture
debout, les bras levés, un déplacement, la pause et le choix d'une image.
La caméra englobe le trajet pour garder les chaussures visibles. Les sources :

- Déplacement : `.local/runtime-holdout-02/motions/a5f6748dd50a4fda8292708a04b8513b-processed.npz`.
- Posture : `.local/runtime-mcp-01/motions/d9747ab538784ef19309c8aafbe625c4-processed.npz`, graine 1302.
- Départ indépendant : `.local/runtime-mcp-01/motions/60303b26bf1b469bb364efb0ab1e4d06-processed.npz`, graine 1301.

Le bouton de mesure parcourt les sommets réellement déformés du VRM, après
mise à jour des os et des contraintes. Les deux séquences de 120 poses donnent :

| Mesure | Déplacement | Bras levés |
|---|---|---|
| Échelle uniforme | 1,05102644 | 1,05102644 |
| Erreur maximale des hanches | < 5 × 10⁻¹⁶ m | < 3 × 10⁻¹⁶ m |
| Pénétration du sol mesurée | 0 | 0 |
| Hauteur du sommet le plus bas, selon la pose | 1,19–4,29 cm | 1,87–2,09 cm |

**Les chaussures flottent encore.** L'absence de pénétration n'est pas une
preuve de contact. La vue n'annonce aucun appui validé et ne corrige pas
silencieusement la hauteur. Le raccord en direct et l'adaptation des appuis à
cette morphologie restent à réaliser avant d'utiliser l'apparence pour valider
T07–T08. Les doigts restent dans leur pose propre au modèle ; aucune prise
physique n'est revendiquée.

Les tests JavaScript vérifient le sens du cap, les rotations composées et la
position mondiale des hanches sous une hiérarchie translatée et redimensionnée.
Les tests Python vérifient l'empreinte de l'asset et la surface HTTP limitée.
Ces tests de contrat ne remplacent pas l'essai du vrai maillage décrit ci-dessus.
