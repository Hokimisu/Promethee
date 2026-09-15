# Avatar anime pixiv

Première apparence retenue à la demande de l'utilisateur, le 15 septembre 2026.
Le personnage reste remplaçable ; il ne définit ni identité, ni personnalité,
ni comportement attendu. Le téléchargement ne valide pas encore son animation
par le squelette Core d'ARDY.

| Champ | Valeur vérifiée dans le fichier |
|---|---|
| Créateur | pixiv Inc. ; © 2022 pixiv Inc. |
| Nom | `VRM1_Constraint_Twist_Sample`, version `v1.0.1` |
| Dépôt officiel | [pixiv/three-vrm](https://github.com/pixiv/three-vrm) |
| Révision | `1b4fc0cc7ef39a49d62bb7a66dcfeca8f65316f7` |
| Chemin | `packages/three-vrm/examples/models/VRM1_Constraint_Twist_Sample.vrm` |
| SHA-256 | `12c2b97e95e700783a6a550dc0eee2d7880aeedccef9ae67bc4c5a2f0f2631a2` |
| Licence de l'asset | [VRM Public License 1.0](https://vrm.dev/licenses/1.0/) et métadonnées du fichier |
| Usage comme avatar | `avatarPermission: everyone` |
| Usage commercial | `commercialUsage: corporation` |
| Modification | `allowModificationRedistribution` |
| Redistribution | `allowRedistribution: true` |
| Crédit | `creditNotation: unnecessary` ; provenance conservée ici malgré tout |
| Restriction explicite | `allowAntisocialOrHateUsage: false` |

Ces permissions viennent de `extensions.VRMC_vrm.meta`, et non de la licence
MIT du code three-vrm. Le modèle n'est pas réattribué au projet. Son fichier
reste intact et conserve l'intégralité de ses métadonnées de licence.

Téléchargement vérifié, sans compte ni poids de modèle IA :

```sh
python experiments/motion/prepare_avatar.py --output .local/assets/pixiv-vrm
```

Le script refuse d'écraser un dossier et vérifie l'empreinte ainsi que les
permissions relues. Le binaire et sa provenance complète restent locaux.
La vignette embarquée et l'import statique dans Viser ont été inspectés :
personnage féminin anime aux cheveux bruns longs, tee-shirt blanc, short noir
et chaussures noires. Le GLB conserve ses textures dans cet aperçu local.
Viser n'expose pas les articulations d'un GLB importé via son `GlbHandle` :
le retargeting et le pilotage de ce maillage restent à effectuer. Ne pas annoncer
cet avatar comme un corps déjà pilotable.
