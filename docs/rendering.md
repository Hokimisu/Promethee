# Rendu en lecture seule

Le visualiseur affiche un snapshot SQLite existant, les repères des objets par ID et le squelette Core exporté lors de T02. Il n'instancie pas de runtime d'exécution, ne crée pas de base, ne migre pas et n'annonce aucun succès. Les commandes logiques restent en deux dimensions.

## Installation et lancement

Depuis la racine du dépôt, sous Windows ou Linux :

```sh
uv sync --locked --extra viewer
uv run --extra viewer python -m promethee.build_viewer
uv run --extra viewer promethee-view --database .local/viewer-check-01/world.sqlite3 --skeleton .local/motion-holdout-01/conventions.json
```

Remplacer les chemins par une base existante et le `conventions.json` de votre [essai T02](../experiments/motion/README.md). Ouvrir `http://localhost:2335`. Le serveur écoute uniquement sur la boucle locale. Le premier lancement construit le client Web du fork Viser épinglé. Sous Windows, la commande de préparation contourne son appel à un script `npm` sans extension, qui échoue avec `WinError 193` ; elle invoque le point d'entrée JavaScript avec Node 20.19.0. Elle ne change pas le code du paquet Viser.

L'option `viewer` ajoute NumPy et Viser ; elle n'ajoute ni PyTorch ni ARDY ni poids. `uv sync --locked` sans cette option conserve le socle CPU. Les installations et caches ne sont pas versionnés. Les dépendances du client Web restent celles du visualiseur amont ; leur installation a signalé 13 vulnérabilités, sans mise à jour automatique de dépendances pendant cet essai.

Pour lire un enregistrement réel sans le faire passer pour une action du monde :

```sh
uv run --extra viewer promethee-view --database .local/viewer-check-01/world.sqlite3 --skeleton .local/motion-holdout-01/conventions.json --motion .local/motion-holdout-01/301-processed.npz
```

Le contrôle « Lire le mouvement » démarre la lecture ; « Pose » permet de scruter une image. Le NPZ doit contenir `posed_joints` de forme `[T,27,3]` et sa cadence `fps`. Le chargeur refuse les tableaux pickle, formes incompatibles, valeurs non finies et cadences invalides. Les coordonnées mondiales sont conservées, sans recentrage ni ajout de la position logique. Le squelette affiché devient alors celui de l'enregistrement ; ce mode est identifié comme lecture de test.

## Coordonnées et apparence

La conversion est centralisée dans [rendering.py](../src/promethee/rendering.py) : `[x,y]` logique → `[x,hauteur,y]` dans Viser, Y vertical. Une case de grille représente un mètre. Les repères X et Y logique sont espacés d'un mètre de l'origine. Le cap nul regarde vers +Z et le cap positif tourne vers +X.

Sans mouvement, `rest_pose` utilise les 27 articulations neutres réellement exportées. Le point le plus bas est posé sur le sol, puis la silhouette est translatée vers la position logique. L'option `--heading 1.5707963267948966` permet le contrôle d'un quart de tour sans changer le monde. Cette pose neutre de diagnostic ne prétend pas représenter une posture observée ou un équilibre physique. Elle n'impose aucune apparence finale.

Chaque objet conserve son ID dans le chemin de scène. Aucun asset 3D du catalogue n'est encore livré : un repère indique l'ID, le type et « asset absent ». Rendre une chaise logique sous forme de repère ne valide pas l'assise. La géométrie utilisable arrive dans T08. Le visualiseur relit le snapshot toutes les 250 ms ; une erreur de lecture conserve le dernier état avec une indication d'indisponibilité.

## Vérifications reproductibles

Créer plusieurs objets avec `promethee act`, dans une base `fixture` dédiée, aux positions choisies librement. Les consulter dans le rendu, fermer celui-ci, puis le rouvrir sur la même base. Déplacer un objet par une nouvelle commande logique et vérifier la mise à jour du repère. Ne pas lancer `demo` pour obtenir une disposition imposée.

```sh
uv run --extra viewer python experiments/motion/verify_rendering.py --database .local/viewer-check-01/world.sqlite3 --skeleton .local/motion-holdout-01/conventions.json --motion .local/motion-holdout-01/301-processed.npz
```

Le contrôle compare les coordonnées de lecture au NPZ, vérifie les translations d'un mètre sur chaque axe et le quart de tour sur le vrai squelette, puis vérifie que le fichier SQLite garde le même SHA-256. L'essai local retrouve les objets en `[1,0]`, `[-2,3]` et `[0,-4]`, le squelette de 27 articulations mesure 1,684 m entre ses extrêmes verticaux et les 120 poses conservent leur cadence de 20 Hz. Ce sont des fixtures techniques, exclues de la mémoire de l'agent.

Les tests CPU couvrent réouverture sans écriture, refus de création d'une base absente, échelle, orientation et coordonnées invalides. L'inspection visuelle complète ces vérifications ; le rendu ne mesure pas les collisions ni la validité des contacts.
