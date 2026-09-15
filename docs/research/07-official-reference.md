# ARDY : comparaison de référence et corrections d'intégration

Recherche et essais du 16 septembre 2026. Ils concernent la locomotion et sa
conversion vers Ariane, pas la voix, le visage ou la manipulation d'un téléphone.
Les trois recherches parallèles portent sur le débit du contrôleur, la commande
de marche/arrêt et les appuis VRM. Leurs constats sont confrontés aux archives
réelles ; une proposition de correction n'est pas une capacité validée.

## Référence NVIDIA vérifiée

La copie officielle étudiée est `nv-tlabs/ardy` à la révision
`693f74d13b3d04a0a22ce127ee79c929dd89756b`, avec Core Horizon40, 20 Hz.

- La démo conserve les **caractéristiques explicites normalisées** retournées
  par le modèle. Elle les recadre puis l'API les encode à nouveau ; elle ne
  transmet pas directement des latents persistants. Son historique par défaut
  contient quatre poses, et sa fenêtre totale est limitée à 200 poses.
- Son filtre de contacts est désactivé par défaut. Même activé, il n'est appelé
  que si une contrainte tombe dans le bloc produit. Après correction, la démo
  reconstruit elle aussi les caractéristiques depuis les nouvelles poses.
- Le contrôle de vitesse intègre une transition depuis la vitesse courante sur
  deux secondes et place des contraintes de position espacées de dix poses.
  Une cible de position lointaine seule ne précise pas quand commencer à marcher.
- Une contrainte `FullBodyConstraintSet` utilise les positions, la racine et
  l'orientation générale. Les matrices de rotation fournies à cet objet ne
  deviennent pas toutes des contraintes du modèle.

Sources primaires : [génération officielle](https://github.com/nv-tlabs/ardy/blob/693f74d13b3d04a0a22ce127ee79c929dd89756b/scripts/interactive_demo/generation.py),
[budget de fenêtre](https://github.com/nv-tlabs/ardy/blob/693f74d13b3d04a0a22ce127ee79c929dd89756b/scripts/interactive_demo/window_budget.py),
[commande de vitesse](https://github.com/nv-tlabs/ardy/blob/693f74d13b3d04a0a22ce127ee79c929dd89756b/scripts/interactive_demo/gen_constraints.py#L156),
[contraintes](https://github.com/nv-tlabs/ardy/blob/693f74d13b3d04a0a22ce127ee79c929dd89756b/ardy/constraints.py),
[papier, notamment limites physiques](https://research.nvidia.com/labs/sil/projects/ardy/assets/ardy_paper.pdf).

## Défaut de fenêtre corrigé et essai réel

Le contrôleur pouvait demander 160 poses d'historique et 120 poses futures,
soit une fenêtre de 280. `generation_window` la limite désormais à 200.
Une cible trop éloignée est omise jusqu'à ce que son véritable instant entre
dans la fenêtre ; elle n'est jamais rapprochée artificiellement.

L'essai `runtime-window-01`, graine 148124, observe neuf secondes d'immobilité
avant de demander deux déplacements et deux postures. Les douze blocs respectent
le budget ; les quatre actions terminent. Le premier calcul utilise bien 160
poses observées, une fenêtre de 200 et aucune cible finale prématurée.
Les cibles sont `(0 ; 0,75)` puis `(0,35 ; 0,45)`.

Cela ne qualifie pas la naturalité : cinq attentes subsistent pendant la lecture,
et l'arrivée conserve une posture de pas. L'essai `runtime-window-holdout-01`,
graine 148125, échoue dès la création du corps sur une correction de sol de plus
de 5 cm ; aucune des quatre actions n'y est exécutée. Ce refus initial précède
la continuation et ne mesure donc pas l'effet du nouveau budget.

La qualification interroge maintenant le contrôleur toutes les 10 ms au lieu
de 50 ms, pour réellement observer les poses à 20 Hz sans perdre des intervalles
par dérive de cadence. La graine et cette cadence diffèrent des essais antérieurs :
le passage de quatre actions ne doit pas être attribué au seul plafond de fenêtre.

## Comparer les corrections sur les mêmes propositions

`experiments/motion/compare_postprocessing.py` applique le filtre officiel aux
propositions sauvegardées et mesure aussi le brut et notre résultat archivé.
Il conserve la provenance, les blocs manquants et la durée propre à chaque variante.
Il refuse les essais dont il ne sait pas reconstruire exactement les contraintes.

Sur `official-comparison-03`, issu de `continuous-stance-path-01`, le deuxième
bloc brut pénètre le sol de 21,42 mm ; avec le filtre officiel, de 33,16 mm.
Notre correction élimine cette pénétration, mais peut déformer d'autres parties
du mouvement. Le filtre officiel n'est donc pas un remplacement démontré de
notre validation des semelles. Le troisième bloc contient une pose sans drapeau
d'appui alors qu'un pied pénètre effectivement le sol : **absence de drapeau
prédit et absence de contact géométrique sont deux constats différents**.

Limite essentielle : ces trois variantes utilisent les mêmes propositions,
initialement conditionnées par notre historique corrigé. Il s'agit d'une
comparaison des corrections, **pas de trois sessions génératives indépendantes**.
Les variantes brute et officielle contiennent 120 poses ; la nôtre seulement
80, car le dernier bloc a été refusé. Le rapport l'indique explicitement.

## Expérience indépendante : historique et commande temporelle

`experiments/motion/reference_trial.py` conserve les caractéristiques explicites
de chaque bloc, comme la démo brute, sans appliquer nos corrections. L'autre bras
reconstruit l'historique depuis les poses brutes. Les deux démarrent avec le même
historique archivé de quatre poses et utilisent les mêmes poids, texte, cible,
graine 128124 et nombre d'itérations. Ces sorties sont des **propositions hors
ligne**, jamais des observations d'un corps exécuté.

Leur premier bloc est strictement identique. Après réinjection, les positions
articulaires divergent jusqu'à 16,2 cm au deuxième bloc et 33,4 cm au troisième.
Conserver seulement les positions à 2 mm lors d'un aller-retour ne prouve donc
pas l'équivalence des vitesses et contacts fournis au modèle.

Mais le retard initial existe dans les deux bras : seulement 1,81 cm parcouru
pendant les deux premières secondes. Il précède donc la reconstruction entre
blocs et l'adaptation VRM.

Une seconde expérience ajoute des objectifs de racine espacés de 0,5 seconde :
accélération sur deux secondes, décélération sur deux secondes, puis position
stable. Ce profil triangulaire de vitesse est une adaptation expérimentale du
principe de commande NVIDIA, pas une reproduction de son pilotage interactif.
Les jambes, bras et appuis restent générés par ARDY. Une variante remplace le
texte de marche par « A person is standing. » après quatre secondes, en conservant
l'historique. Aucun terminal de jambes synthétique n'est ajouté.

| Archive locale | Déplacement à 2 s | Vitesse maximale, frontières incluses | Erreur finale |
|---|---:|---:|---:|
| `reference-features-02` : cible finale seule | 1,81 cm | 1,273 m/s | 4,71 mm |
| `reference-rawposes-01` : même commande, historique reconstruit | 1,81 cm | 1,360 m/s | 8,64 mm |
| `reference-sparse-path-01` : trajectoire clairsemée | 49,93 cm | 0,740 m/s | 12,24 mm |
| `reference-sparse-settle-01` : même trajectoire, puis repos | 49,93 cm | 0,740 m/s | 8,46 mm |

Les déplacements du tableau mesurent la racine entre la première pose et celle
à l'indice 39. La variante repos ne change pas les deux premiers blocs ; elle
réduit l'agitation des articulations dans le dernier. Une seconde graine,
`reference-sparse-settle-holdout-01` (128125), finit à 7,68 mm de la cible, mais
contient une pose sans drapeau d'appui prédit au premier bloc.

Les rendus du maillage Core à 20 Hz sont archivés sous `render/motion.mp4`.
Les planches extraites à 2 images/s montrent le départ, les pas et le repos,
ainsi que des pénétrations résiduelles colorées en rouge. Cette inspection
confirme la différence de départ ; elle ne qualifie ni toute la fluidité,
ni les contacts VRM, ni une interaction en direct.

Le passage hors ligne des mêmes propositions dans nos corrections Core reste
refusé dès le premier bloc pour les deux graines : P95 de glissement de
0,074373 m/s au lieu des 0,05 autorisés pour 128124 ; absence de drapeau d'appui
pour 128125. Les pénétrations brutes atteignent respectivement 22,35 et 21,36 mm.
Les chaînes sont arrêtées au premier refus, sans produire de rejeu VRM qualifié.
La commande améliore donc le départ mesuré, mais n'est pas encore retenue pour
le contrôleur en direct. Ces mesures de conversion ne réinjectent pas leur
résultat dans le modèle et ne constituent pas un essai de boucle complète.

Un second traitement CPU applique le filtre NVIDIA avec les objectifs exacts
aux indices 9, 19, 29 et 39, puis reconstruit les contacts via `ArdyMotionRep`,
comme la démo. Les deux séries sont encore refusées au premier bloc par la
projection d'appui. Aucun drapeau n'est modifié à la main. Sur la graine 128125,
la pose brute sans drapeau n'est pas un vol : les deux semelles traversent le
sol, avec le pied gauche en déplacement. Remplacer le drapeau ne suffirait donc
pas à produire un appui valide.

## Glissement introduit par une transition VRM : correction vérifiée

L'essai `continuous-reference-history4-02` passait les contrôles Core puis
échouait sur le glissement VRM. Son pied gauche initial se trouvait à 0,2787 mm
du sol, juste au-dessus du seuil de contact de 0,1 mm. Au nouvel appui,
le solveur créait l'ancrage depuis le retarget brut au lieu de la dernière
apparence visible. La transition déplaçait alors cette cheville de 14,321 mm.

Le nouvel ancrage conserve maintenant les coordonnées horizontales et les
rotations visibles. Seule sa hauteur est projetée vers le sol, comme pour les
autres nouveaux appuis. Le seuil de contact et les limites de glissement restent
inchangés. Un test couvre des pieds immédiatement de part et d'autre du seuil,
y compris la hauteur mesurée de cet essai.

Le rejeu des **mêmes trois blocs et du même état initial** passe désormais les
contrôles VRM : `continuous-reference-history4-appearance-03-initial-anchor`.
Au dernier bloc, le P95 du glissement passe de 0,070468 à 0,013035 m/s ; le
déplacement horizontal de la cheville pendant la transition devient négligeable
numériquement. Les 40 poses ont un contact mesuré. Ce résultat corrige un défaut
de conversion ; il ne démontre pas une meilleure génération d'ARDY.

Un autre refus reste séparé : sur `continuous-stance-01`, un changement de pivot
de semelle entraîne une variation de bassin de 28,741 mm entre deux poses.
La correction d'ancrage ci-dessus ne prétend pas résoudre ce cas.

## Débit et prochaine décision

L'analyse de `runtime-window-01` distingue les attentes initiales
(6,512 / 6,029 / 5,080 / 5,440 s) des cinq attentes pendant la lecture
(0,800 / 0,611 / 0,776 / 1,307 / 0,784 s).
Chaque suite est demandée avec environ 1,95 seconde d'avance, alors que génération
et préparation prennent souvent 2,4 à 3,2 secondes. Un validateur Python persistant
pourrait économiser une partie du démarrage, mais ne suffit pas à lui seul.

L'autre défaut mesuré est temporel : 40 poses lues de l'indice 0 à 39 durent
1,95 seconde. Notre correction forçait en plus la première pose future à répéter
la dernière pose observée, annulant momentanément sa vitesse. Il faut conserver
une origine observée à t=0 puis 40 nouvelles poses jusqu'à t=2 s, sans compter
l'origine comme un nouvel échantillon dans l'historique. Ce changement touche
le contrôleur, les archives et la préparation VRM ; il doit être vérifié ensemble.

Le correctif est implémenté pour le mode continu : les 40 poses futures restent
distinctes de l'origine observée, conservée sans arrondi et sans nouvelle
résolution de l'apparence. Les contrôles de contact incluent cette frontière.
Un rejeu CPU d'un bloc réel conserve exactement l'apparence initiale et passe
les contrôles sur les 41 poses Core et VRM. Le test d'orchestration de trois
blocs préchargés mesure 6,000003 secondes, contre 5,850003 avant correction.

L'essai réel `runtime-origin-01`, même graine 148124 et mêmes demandes que
`runtime-window-01`, termine les deux déplacements et la levée des bras. La
posture de repos échoue sur une vitesse de glissement Core maximale de
0,292382 m/s ; la limite de 0,2 reste appliquée. Une attente survient pendant
la lecture. Le changement d'historique et des trajectoires rend cette série
insuffisante pour attribuer la diminution des attentes au seul intervalle ajouté.

Le glissement de cette posture provenait de la frontière origine/premier futur :
les ancrages Core étaient initialisés après cette frontière. L'origine observée
est maintenant incluse avant la stabilisation, puis restaurée exactement avant
les contrôles. Le rejeu du même bloc mesure un maximum de 0,007752 m/s côté Core
et de 0,016670 m/s côté VRM, avec l'origine conservée exactement.

L'essai suivant, `runtime-origin-02`, termine trois actions sur quatre et ne
rencontre aucune attente de tampon pendant la lecture. Le déplacement refusé
propose une arrivée à `[0.0300929, 0.6974089]` pour une cible `[0, 0.75]`, soit
6,059 cm d'écart. Ce dernier bloc n'a pas été exécuté : la limite d'arrivée de
5 cm le rejetait avant la préparation VRM. L'aperçu à l'échelle a permis à
l'utilisateur de préciser que cet écart n'est pas un défaut pertinent pour la
marche libre, et qu'une tolérance d'un mètre convient à cet usage.

Les critères v5 séparent donc la marche libre (1 m) de la stabilité sur place
(5 cm). La position réellement atteinte reste persistée ; aucune correction
vers la destination n'est ajoutée. Les archives des essais précédents gardent
leurs critères et résultats d'origine. Les contrôles de continuité, de sol et
de contact ne sont pas modifiés par cette décision. Les régressions vérifient
notamment l'acceptation de 6,059 cm, le rejet au-delà d'un mètre et la conservation
de la position observée. La suite Python compte 499 tests réussis et deux ignorés.

La priorité perceptive est la fluidité visible, les pauses et la posture. Une
erreur de placement en marche libre ne doit plus être présentée comme le
principal blocage de la naturalité.

Un défaut distinct du contrôle des mains apparaît après un arrêt au milieu
d'une transition d'alignement : l'apparence restaurée contient déjà son poids
d'alignement, mais la mesure lui appliquait ce poids une seconde fois. La cible
de contrôle de l'origine est désormais la position visible restaurée. Sur le
même rejeu VRM, l'erreur artificielle de 29,238 mm devient nulle ; les seuils
restent inchangés. Les régressions couvrent les poids intermédiaires 0,1, 0,4
et 0,5 ainsi que leurs extrêmes. Les 105 tests Python ciblés et les 15 tests
JavaScript passent après cette correction.

## Répétition théâtrale de 60 secondes

À la demande explicite de l'utilisateur, une scène locale « Le dernier mail »
fait rentrer Ariane du travail en colère. C'est une répétition préparée, exclue
du comportement par défaut et de la mémoire, et non une improvisation autonome.
Les fichiers locaux `theatre-anger-01` et `theatre-anger-02` conservent les prompts,
poses, voix, repères temporels et scripts de rendu.

ARDY génère trente horizons successifs de deux secondes en conservant ses
caractéristiques explicites. Un essai ne change que la longueur d'historique,
de 40 à 4 poses : mêmes huit encodages textuels et premier bloc identique.
L'historique court augmente l'amplitude verticale des mains pendant deux
tirades de 10 à 37–50 cm et de 2 à 34–36 cm. Le passage de 16 à 24 secondes
reste moins mobile. Cette comparaison ne démontre pas que quatre poses sont
optimales pour toutes les actions.

La lecture utilise 3 600 poses d'apparence à 60 Hz, obtenues par interpolation
des rotations locales, avec correction verticale du maillage des chaussures.
Elle ne passe pas par le contrôleur du monde ni par ses contrôles stricts ; elle
ne qualifie donc pas les appuis physiques. Le rendu 3D s'exécute en temps réel,
tandis que mouvements et dialogue sont préparés. Une piste française de
60 secondes, produite localement avec Microsoft Hortense, pilote l'horloge de
lecture. L'ouverture de bouche suit l'amplitude audio ; ce n'est pas un
alignement phonétique. L'objectif utilisateur reste l'improvisation cohérente
entre parole et corps, que cette répétition ne prétend pas livrer.

La lecture complète de la seconde variante a duré 60,022 secondes réelles pour
60 secondes de piste, avec 8 632 images rendues et un temps inter-image médian
de 6,9 ms sur cet écran. Cela mesure le lecteur, pas la génération en direct.
L'utilisateur a accepté les mouvements pour cet exercice, en les jugeant encore
bancals, et demandé de remplacer la voix.

Une voix synthétique Qwen a ensuite été approuvée à l'écoute. Ses six répliques
clonées ont été assemblées dans une nouvelle piste de 60 secondes, sans découpe
ni accélération ; les repères de sous-titres et de bouche suivent ces nouveaux
fichiers. La mesure de lecture ci-dessus reste celle de l'ancienne piste.
Les moteurs vocaux et leurs mesures sont décrits dans la
[comparaison des voix locales](08-local-voice.md).
