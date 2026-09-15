# Session VRM en direct

Le personnage [pixiv](assets/pixiv-vrm-sample.md) peut maintenant afficher une
session corporelle active et lui soumettre des commandes. Le même contrôleur
cinématique et le même registre d'exécution servent la page et les outils MCP.
Aucun objet ni comportement n'est lancé à l'ouverture de la page.

## Lancer

Installer le [pilote ARDY](motion-validation.md) et télécharger l'avatar selon sa
fiche de provenance. Construire le rendu :

```sh
npm --prefix web/avatar ci --ignore-scripts
npm --prefix web/avatar run build
```

Ajouter `--avatar` et `--web-root` à la commande du pilote. Exemple avec
l'environnement ARDY installé sous WSL ; adapter les chemins locaux :

```sh
uv run --extra avatar promethee --data-dir .local/live-avatar run --ardy-python /root/.local/share/promethee/ardy-env/bin/python --checkpoint-root /root/.local/share/promethee/checkpoints --wsl Ubuntu-22.04 --object-interactions --avatar .local/assets/pixiv-vrm/VRM1_Constraint_Twist_Sample.vrm --web-root web/avatar/dist --port 2365
```

Ouvrir `http://127.0.0.1:2365/`. Ne pas ouvrir un second contrôleur sur le même
dossier. Une session neuve doit recevoir sa première pose par le pilote ;
le chargement reste affiché jusqu'à ce qu'un état articulé soit disponible.
Les commandes de corps conservent les prérequis et refus du pilote ARDY.

Le panneau propose création de doudou ou balle, prise, dépôt aux coordonnées,
déplacement et posture. Les capacités absentes du contrôleur sont désactivées.
Y est la hauteur ; les objets libres gardent leur transformation, sans gravité.
L'arrêt reste une demande jusqu'à la confirmation du contrôleur.

## Cohérence de la vue

Le contrôleur publie un instantané corps/objets après chaque pas, à 20 Hz.
La page consulte le dernier instantané, sans inventer de poses corporelles
intermédiaires. Un flux vieux de plus d'une seconde est refusé ; la page
signale la perte et désactive les nouvelles actions. Un changement de session
exige de recharger la page. Une erreur de rendu reste visible jusqu'au
rechargement ; recevoir de nouveaux états ne la masque pas.

La [portée du personnage](avatar-arm-reach.md) est vérifiée par le contrôleur.
Pendant une interaction, la main visible est adaptée au poignet Core. Le poids
de cette adaptation varie sur 0,25 s à l'approche et après libération pour
éviter une commutation brutale entre les deux morphologies. Dès qu'un objet
est tenu, le poids vaut un : son attachement reste celui de l'observation.
Cette transition est une correction d'apparence, pas une trajectoire physique.
Les doigts, la peau et les appuis ne sont pas validés par ce calcul.

Le transport HTTP n'écoute que sur `127.0.0.1`. Les mutations exigent le Host
et l'Origin de la session ainsi qu'un JSON borné. Les routes statiques sont
énumérées et ne donnent aucun accès aux dossiers. Chaque action reçoit un ID
et la révision courante ; la page ne retransmet pas automatiquement une
mutation dont la réponse manque. Recharger consulte l'état sans rejouer l'action.

## Vérification locale

Le 15 septembre 2026, une session réelle du contrôleur, initialisée depuis une
pose Core archivée, a été pilotée dans le navigateur avec le vrai maillage
pixiv. La balle `sample` a été prise, conservée lors du rechargement, déposée,
puis reprise. Une dépose interrompue par le bouton d'arrêt a fini `cancelled`
avec la balle encore tenue. Le redémarrage du serveur a restauré cet état.
La création de `peluche-ui` en `[0.3, 1.1, 0.4]` a ensuite ajouté sa géométrie
au même monde sans modifier l'attachement de la balle.
Les exécutions et observations sont conservées localement dans
`.local/object-controller-qualification-07/live-browser.json`.

Ces commandes sont manuelles et restent des données de qualification exclues
de la mémoire personnelle. Elles ne valident ni Astra ni une nouvelle
génération ARDY. Les [essais sur plusieurs positions et géométries](spatial-objects.md)
qualifient séparément le contrôleur d'objets.

Les tests HTTP utilisent des poses analytiques : publication immuable,
réémission idempotente, arrêt avant départ et pendant l'approche ou après
contact, refus des requêtes étrangères, flux périmé et chemins inconnus.
Les tests JavaScript vérifient aussi les extrémités et l'absence d'accumulation
du mélange des mains. Ils ne remplacent pas l'inspection du maillage réel.

## Apparence préparée (expérimental)

Ajouter `--prepare-avatar` pour calculer les poses VRM avant leur lecture.
Node.js et les dépendances de `web/avatar` doivent rester installés : construire
le seul fichier du navigateur ne suffit pas. Une base existante doit être au
schéma 10, avec sauvegarde vérifiée lors de sa migration.

Le contrôleur prépare la géométrie puis la fait vérifier dans deux processus
annulables. Le corps conserve sa dernière observation pendant cette préparation.
Chaque pose jouée persiste ensemble le corps Core, les objets, les rotations VRM
et la correction verticale. Le navigateur applique cet instantané sans refaire
l'alignement des mains. Après un arrêt ou un redémarrage, la même apparence est
restaurée. Une session contenant ces poses exige ce mode pour continuer.

Les instantanés d'apparence de version 2 conservent aussi le poids d'alignement
de chaque main. La transition dure 0,25 s à partir du poids sauvegardé, y compris
après une interruption partielle. Un objet tenu exige un alignement complet.
Le premier essai sans cette transition produisait un saut de 13,4 cm ; il a été
refusé avant lecture par la limite de continuité de 2 cm.

Les qualifications locales `prepared-controller-qualification-02` (balle) et
`prepared-controller-qualification-03` (doudou) couvrent prise, dépôt, arrêt avant
et après contact, reprise et refus d'actions invalides. Le second essai couvre
également l'arrêt pendant l'alignement partiel et sa restauration exacte. Ces
essais utilisent une pose Core archivée, pas une nouvelle génération ARDY.
La relecture des 408 poses du doudou conserve les instantanés VRM : le maillage
affiché a été inspecté dans le navigateur, avec contact du pied gauche sur les
408 poses et le pied droit à environ 3,5 mm du sol. Les doigts et l'équilibre
physique ne sont pas validés. Ce mode ne clôt pas T07.

Le premier essai avec nouvelles générations ARDY et apparence préparée
(`.local/runtime-prepared-holdout-01`, graines 77123–77127) donne deux changements
de posture terminés et deux déplacements échoués. Le déplacement vers
`[0.25, 0.15]` est refusé pour absence d'appui prédit aux images 76 et 93 ; celui
vers `[-0.12, 0.08]` dépasse les 5 cm de correction verticale de l'apparence.
Aucun des deux déplacements refusés n'est joué ni déclaré terminé.

Les deux postures durent environ 10,3 s chacune, génération et préparation
comprises, avec 120 poses préparées par posture. Chaque pose a au moins un contact
de surface mesuré ; la vitesse maximale des points de contact est de 0,017 m/s
et la discontinuité initiale maximale de 19,35 mm. La relecture de 533 observations
échantillonnées dans le temps a été inspectée dans le navigateur, bras levés puis
retour debout. Elle conserve les poses préparées, y compris pendant les attentes.
Le contrôle des appuis prédit et la limite de correction restent donc deux causes
d'échec à résoudre ; ces résultats ne valident pas encore les déplacements.

`experiments/motion/qualify_runtime.py --avatar <fichier.vrm>` reproduit cette voie
avec des cibles et une graine choisies avant l'essai. Le dossier de sortie doit
être neuf. Il conserve les sources, la configuration, les résultats et les
observations horodatées ; ces dernières ne sont pas une vidéo à cadence garantie.

La correction de mise au sol respecte désormais ensemble la limite de 5 cm du
bassin et la tolérance de contact de 0,1 mm, au lieu de forcer systématiquement
la semelle à exactement zéro. Un dépassement qui laisserait la surface hors de
cette tolérance reste refusé. Les contrôles finaux du maillage, des vitesses et
de la continuité restent identiques.

Sur le déplacement refusé du premier essai, le dépassement était de 0,094 mm
à la pose 25. Sa relecture corrigée passe les 120 poses, avec une correction
plafonnée à 5 cm, un contact mesuré à chaque pose et une vitesse de surface
maximale de 0,020 m/s. Il s'agit d'une recalibration sur une trajectoire archivée,
pas d'une nouvelle réussite du runtime historique.

Un nouvel essai distinct (`.local/runtime-prepared-holdout-02`, graines
87123–87127) termine le déplacement vers `[-0.18, 0.22]` avec 4 mm d'erreur,
puis les postures bras levés et debout. Le retour vers `[0.14, -0.08]` reste
refusé pour absence d'appui prédit. Le déplacement préparé conserve 120 contacts
de surface sur 120 poses, une vitesse maximale de 0,038 m/s et une correction
verticale maximale de 49,5 mm. T07 reste ouvert.
