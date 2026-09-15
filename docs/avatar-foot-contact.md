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

## Essai d'adaptation, hors session

`measure-feet.mjs --settle` teste une translation verticale du bassin visible
pour amener la chaussure la plus basse au sol. Les cibles des mains associées
aux objets restent aux positions Core observées ; une nouvelle résolution des
bras compense la translation. Les longueurs des membres ne changent pas.
Sur les deux déplacements de calibration, cette translation donne un contact
à chaque image mais révèle du glissement : maximum/P95 de 1,254/0,539 m/s pour
le premier trajet 15, et 0,315/0,071 m/s pour le retour 16. Elle ne suffit donc
pas à adapter la marche.

L'option `--plant` teste en plus un ancrage des chevilles et des orientations
de pied pendant les phases d'appui prédites par ARDY. Les jambes sont résolues
sur la géométrie VRM. Le bassin descend seulement pour rendre ces cibles
accessibles ; une enveloppe calculée sur toute la séquence limite les variations.
Un dégagement de 1 cm protège le pied libre. La correction résiduelle est
mesurée sur le maillage réel après résolution. La correction totale de racine
reste limitée à 5 cm et 15 mm par image. Il ne s'agit pas d'un solveur physique.

Les essais initiaux d'ancrage dépassaient la limite de variation verticale aux
changements d'appui. L'enveloppe anticipe désormais les besoins futurs avec une
pente de 13 mm par image ; la limite finale de 15 mm reste vérifiée après la
correction du maillage. Le premier trajet 15 dépasse encore 5 cm et demeure
refusé. Aucun seuil final n'est relevé pour le faire passer.

| Calibration | Mode | Contact mesuré | Glissement maximal / P95 | Correction verticale maximale |
|---|---|---:|---:|---:|
| Série 15, premier trajet | Ancrage | Non qualifié | Refus avant mesure complète | Dépasse 5 cm |
| Série 16, retour | Ancrage | 120 / 120 images | 0,03269 / 0,01309 m/s | 28,24 mm |
| Série 13, bras levés | Ancrage | 120 / 120 images | 0,00392 / 0,00170 m/s | 24,08 mm |
| Objets 07, prise/dépôt | Translation seule | 279 / 279 images | Moins de 10⁻⁸ m/s | 17,29 mm |

Le parcours objets conserve la position de la main droite à 3,3 × 10⁻⁸ m près.
Il n'archive pas de contacts ARDY : aucun indicateur d'appui n'y est inventé,
et seul `--settle` est essayé. Les sauts articulaires maximaux mesurés après
adaptation sont respectivement 0,210 m pour le retour 16, 0,171 m pour les bras
levés et 0,0153 m pour les objets. Les faibles vitesses de semelle ne garantissent
donc pas la douceur de tous les membres.

La lecture expérimentale `.local/vrm-plant-preview-01` du retour 16 a été
inspectée dans le navigateur, au départ, au milieu et à l'arrivée. Elle utilise
les poses VRM précalculées, sans deuxième correction. Le bouton de mesure
retrouve exactement les hauteurs du rapport : le point rendu le plus bas reste
entre −2,57 × 10⁻¹¹ et 1,24 × 10⁻¹¹ m. Les bras libres conservent leurs
différences de proportions ; aucune qualité de prise n'est déduite de ce trajet.

Ces résultats proviennent de données ayant servi au réglage, pas d'une nouvelle
qualification indépendante. Les fichiers, sources et empreintes sont archivés
dans `.local/vrm-grounding-calibration-01`. Un échec est écrit explicitement dans
le rapport, avec le nombre d'images effectivement mesurées ; il ne vaut pas une
correction réussie.

Pour reproduire l'essai, exporter les indicateurs réellement présents dans le
NPZ, puis choisir le mode de mesure :

```sh
python experiments/motion/export_foot_trial.py --motion mouvement.npz --skeleton conventions.json --output mouvement.json
node web/avatar/measure-feet.mjs .local/assets/pixiv-vrm/VRM1_Constraint_Twist_Sample.vrm mouvement.json nouveau-rapport.json --plant
```

`--plant` exige les quatre indicateurs booléens de contact par image ; il refuse
leur absence ou une phase sans appui prédit. `--settle` n'en a pas besoin. Le
mode sans option conserve la mesure du rendu original.

`foot-planting-trial.js` n'est importé ni par le rendu en direct ni par le pilote.
Avant un raccord, le contrôleur doit vérifier la portée des bras avec le
décalage du bassin, transmettre les appuis et les corrections avec les poses,
et conserver ces contraintes pendant les annulations et reprises. L'actuel
profil de bras suppose les hanches à leur position Core : activer cette
correction uniquement dans le navigateur contournerait sa vérification.
Le rendu livré reste inchangé et T07 reste ouvert.

## Poses préparées avant lecture

L'outil de mesure peut exporter les rotations mondiales des 22 os normalisés
et le décalage vertical du bassin. Il ne transmet aucune longueur de membre
ni position locale permettant d'étirer le squelette. L'archive identifie
l'asset, le document Core exact par SHA-256, l'échelle, le mode de correction
et les mains alignées.

```sh
node web/avatar/measure-feet.mjs avatar.vrm mouvement.json nouveau-rapport.json --plant --poses nouvelles-poses.json
```

Chaque pose est sérialisée en JSON, puis le squelette est remis dans sa pose
Core sans adaptation des mains. Le rejeu applique les rotations enregistrées
et la position corrigée du bassin, sans relancer la résolution des membres.
Les contacts et les erreurs des mains sont mesurés sur ce résultat rejoué.
Une pose mal formée est refusée avant toute modification du squelette.

L'export exige la totalité des images à 20 Hz, un contact géométrique à chaque
image, un glissement maximal/P95 inférieur ou égal à 0,20/0,05 m/s, aucune
pénétration de chaussure au-delà de 1 mm, un déplacement articulaire maximal
de 0,30 m par image et une erreur des mains alignées au plus égale à 10 µm.
Les limites de correction verticale restent 5 cm et 15 mm par image. Un refus
ne produit pas de fichier de poses ; son rapport de mesure reste consultable.
Ces seuils ne qualifient ni équilibre physique ni naturel du mouvement.

Sur les mêmes données de calibration, les 279 images objets 07, les 120 images
du retour 16 et les 120 images bras levés 13 passent ce chemin. Les vitesses
de semelle retrouvent les mesures du tableau précédent ; la main droite du
parcours objets reste à moins de 3,3 × 10⁻⁸ m de sa cible après rejeu. Le
premier trajet 15 reste refusé avant export pour dépassement de 5 cm.
Les sources, entrées, rapports et poses sont conservés dans
`.local/prepared-poses-qualification-02`.

Les tests utilisent aussi une hiérarchie tournée, translatée et mise à
l'échelle : la pose ne dépend pas de l'état précédent et les longueurs restent
inchangées. Les huit tests web passent. Cette préparation reste hors session :
le lancement asynchrone et la persistance de la pose d'apparence avec la pose
Core restent à raccorder avant
d'activer l'adaptation dans le rendu en direct.

## Vérification Python des poses préparées

`prepared_avatar.load_prepared_poses(path, motion_bytes)` vérifie l'archive
contre les octets exacts du document envoyé à la préparation. Il refuse un
autre asset, une autre échelle, un mauvais nombre de poses, des rotations
invalides et des décalages de bassin hors limites. La liste des mains alignées
doit correspondre aux attachements du document. L'ancrage exige les indicateurs
de contact archivés ; une translation seule ne peut modifier les jambes.

Le contrôle compare les rotations non adaptées à Core, puis reconstruit les
mains sur les longueurs VRM du profil. Chaque main alignée doit rester à moins
de 10 µm de sa cible Core, avec une portée encore valide après déplacement du
bassin. Le chargement ne modifie aucun monde. Les contacts du maillage restent
mesurés par le producteur Three.js ; ce contrôle Python ne les recalcule pas.

Le premier essai a révélé une différence entre l'orthogonalisation SVD utilisée
en Python et la conversion matrice/quaternion du rendu. Pour une matrice Core
légèrement imparfaite, ces deux conversions diffèrent : jusqu'à 5,04 × 10⁻⁵
sur un coefficient de rotation de la séquence retour 16. Python utilise
désormais la même conversion que Three.js 0.186.0, y compris dans le contrôle
de portée existant. Le seuil de comparaison reste inchangé.

Les 519 poses passent alors la vérification, avec un écart maximal de
2,11 × 10⁻¹⁵ sur les rotations non adaptées. Les sept parcours objets
antérieurs repassent aussi le contrôle de portée sur 1 955 poses. Un export
supplémentaire de 278 poses du parcours objets 02 passe le chargeur avec la
main gauche alignée ; son erreur visible maximale reste de 3,64 × 10⁻⁸ m.
Les rapports
sont conservés dans `.local/prepared-validator-qualification-02` et
`.local/avatar-offset-reach-qualification-02`. Ces données restent des
calibrations, exclues de la mémoire personnelle. Le contrôleur en direct
n'appelle pas encore ce chargeur ; le raccord asynchrone et la persistance
restent nécessaires.

Vérifications du changement : 302 tests Python réussis, deux tests optionnels
ignorés, lint, formatage et construction du paquet réussis.

## Préparation annulable en arrière-plan

`AppearancePreparation` exécute la mesure Three.js, puis le validateur Python
dans deux sous-processus successifs. Un seul travail est admis à la fois.
`submit(document, mode=...)` fige le document et renvoie un identifiant ;
`poll()` ne livre les poses qu'après validation complète. `cancel()` invalide
aussi un résultat terminé mais pas encore consommé. Le prochain travail reçoit
un autre identifiant. Ces méthodes sont appelées par une seule boucle propriétaire.

Un thread supervise les processus ; la validation lourde ne s'exécute pas dans
ce thread. L'essai initial y effectuait aussi la lecture Core et la validation,
avec une pause de scrutation atteignant 122 ms au premier import de NumPy, puis
54 ms après préchargement. La séparation du validateur supprime ces pauses sur
les cas mesurés, au prix du démarrage d'un interpréteur supplémentaire.

Chaque travail garde son document, sa mesure, ses poses et ses diagnostics dans
un dossier distinct. Une erreur de géométrie, de validation ou de délai ne
renvoie aucune pose. Le délai commun est de 60 secondes au maximum ; l'arrêt
termine uniquement le sous-processus lancé pour ce travail, attend sa sortie
et peut le tuer après deux secondes de grâce. Fermer le préparateur annule son
travail et libère ses ressources. Aucune écriture du monde n'a lieu ici.

Sur le vrai VRM et les mêmes séquences de calibration :

| Cas | Résultat | Durée totale |
|---|---|---:|
| Objets 07 | 279 poses préparées et validées | 1,81 s |
| Retour 16 | 120 poses préparées et validées | 1,40 s |
| Bras levés 13 | 120 poses préparées et validées | 1,44 s |
| Premier trajet 15 | Refus géométrique, aucune pose livrée | 0,33 s |

Deux autres essais annulent respectivement le vrai processus géométrique et le
vrai processus de validation. Leur sortie est constatée environ 20,3 ms après
la demande, sans livraison de poses. L'outil scrute toutes les 20 ms ; ses
intervalles maximaux restent entre 20,6 et 21,1 ms pendant les trois préparations
réussies. La sérialisation initiale de `submit`, effectuée une fois dans le
thread appelant, prend séparément 21 à 50 ms. Il ne s'agit ni d'une garantie
temps réel ni d'une mesure du bouton d'arrêt de la session.

Les données sont conservées dans `.local/appearance-process-qualification-03`.
Les essais précédents sont conservés sous les suffixes `01` et `02`. Les tests
de cycle de vie utilisent de vrais sous-processus avec des poses analytiques ;
ils couvrent annulation, résultat tardif, fermeture, délai, refus et isolation
du document soumis. Le raccord à `KinematicController` et la persistance de la
pose visible restent à réaliser avant d'activer ce chemin dans la session.

Vérifications de cette étape : 308 tests Python réussis, deux tests optionnels
ignorés ; lint, formatage et construction du paquet réussis.
