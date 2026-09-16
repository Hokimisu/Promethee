# Génération corporelle par blocs

Le mode expérimental `--continuous-motion` relie désormais la continuation ARDY
au contrôleur en direct. Une action motrice de 120 poses est préparée en trois
blocs de 40 poses futures à 20 Hz. Chaque bloc de lecture conserve aussi sa pose
d'origine observée, soit 41 poses couvrant exactement deux secondes. Le corps commence après validation du premier bloc ;
le suivant est généré et, si demandé, adapté au VRM pendant cette lecture.

Le mode est désactivé par défaut. Il améliore la continuité de la chaîne de
calcul, mais **ne qualifie pas une marche naturelle** : les essais indépendants
conservent des déplacements refusés et des attentes. Il n'ajoute ni physique,
ni freinage, ni animation faciale, ni interpolation du rendu.

## Activer et comparer

Ajouter `--continuous-motion` à la commande de [session VRM](live-avatar.md),
avec `--prepare-avatar` pour vérifier les poses du personnage avant lecture.
Les installations et chemins ARDY restent ceux du [pilote](motion-validation.md).
Aucune migration, dépendance ou modification de données sauvegardées n'est
nécessaire. Retirer l'option restaure la génération par séquences complètes.

Exemple de qualification réelle, avec les environnements installés sous WSL :

```sh
.venv/Scripts/python.exe experiments/motion/qualify_runtime.py --output .local/continuous-new-trial --ardy-python /root/.local/share/promethee/ardy-env/bin/python --checkpoint-root /root/.local/share/promethee/checkpoints --wsl Ubuntu-22.04 --seed 138124 --first-target 0 0.75 --second-target 0.35 0.45 --avatar .local/assets/pixiv-vrm/VRM1_Constraint_Twist_Sample.vrm --continuous-motion
```

Le dossier doit être neuf. `--cancel-first-after 0.3` ajoute une demande d'arrêt
0,3 seconde après le premier début de lecture. Le rapport indique si cette
annulation a effectivement eu lieu ; un mouvement refusé avant départ ne la
valide pas. Les données restent des qualifications exclues de la mémoire.

## Historique, futur et arrêt

Le contrôleur conserve au maximum 160 poses Core observées à 20 Hz. Un trou
dans les observations réinitialise cet historique : les poses intermédiaires
non observées ne sont pas déclarées jouées. Après redémarrage, seul le dernier
checkpoint est restauré ; aucun futur ni historique en mémoire n'est repris.

Pour anticiper, le contexte comprend aussi le bloc validé dont la lecture est
engagée. Ces poses futures sont **comptées séparément** des poses exécutées dans
la requête archivée. Elles ne constituent pas des observations. Un fichier
numérique borné et identifié par SHA-256 transporte ce contexte hors du petit
message JSON. Le processus ARDY vérifie qu'il finit à la pose de départ attendue,
puis reconstruit ses caractéristiques depuis les rotations Core corrigées.
Une erreur de reconstruction de plus de 2 mm est refusée. Les rotations VRM
restent dans leur propre checkpoint et ne sont pas réinjectées dans ARDY.

Un seul bloc futur peut être en calcul, en préparation ou prêt. Sa frontière
inclut le corps, les objets attachés et l'apparence. Avant son démarrage, elle
doit correspondre exactement à l'état observé à la fin du bloc précédent.
Les contraintes de cible finale ne sont vérifiées qu'au dernier bloc ; les
contrôles de géométrie et de continuité s'appliquent à chacun.

La fenêtre totale du modèle est limitée à 200 poses. Une cible située au-delà
n'est transmise que lorsqu'elle entre dans cette fenêtre, à son véritable
instant. La pose d'origine du bloc n'est ni une nouvelle proposition, ni un
échantillon supplémentaire du futur engagé. Les 40 poses brutes restent
archivées séparément ; le bloc corrigé ajoute l'origine pour la lecture.
Ses contacts sont mesurés sur le maillage observé et leur provenance est
indiquée par `anchor_contact_source=observed_skin_geometry`.

Les tentatives supplémentaires conservent ce contexte engagé, une nouvelle
graine et un nouvel ID de travail, avec les limites existantes de trois essais
et 60 secondes. Une proposition refusée n'est jamais jouée. Si aucun bloc
validé n'est prêt, le contrôleur garde la dernière pose et signale l'attente.
Une erreur définitive termine l'action en `failed`, même si un début a été joué.

L'annulation supprime le futur, confirme la pose arrêtée et ignore les résultats
tardifs. Une nouvelle consigne utilise un nouvel ID. Elle attend que les
processus devenus inutiles aient rendu la main. Cet arrêt fige une pose
cinématique ; une transition de freinage physique reste à développer.

L'encodage du texte est réutilisé uniquement à l'intérieur d'une même action et
d'un même processus modèle. Une nouvelle action réencode son texte, même s'il
est identique. Le cache contient une seule entrée, sans persistance ni dépendance
à une ancienne version du modèle. Changer l'encodeur configuré nécessite de
redémarrer le contrôleur. Les identités d'action ne peuvent pas changer de texte.

## Essais réels du 15 septembre 2026

Les poids Core Horizon40 et leur révision restent ceux de la
[décision ARDY](decisions/001-motion-stack.md). Les dossiers ci-dessous contiennent
les requêtes, copies du code, propositions, refus, apparences, observations et
résultats terminaux. `motions/stream-events.jsonl` distingue demande de calcul,
retour du modèle, apparence prête, début de lecture, réserve vide et fin d'action.

| Archive locale | Résultat observé |
|---|---|
| `runtime-continuous-01` | Première intégration : les deux déplacements finissent, avec attentes. Une posture est rejetée à tort parce que sa cible était comparée à la position intermédiaire ; défaut corrigé et couvert par un test. |
| `runtime-continuous-02` | Réutilisation du texte et cible corrigée : deux postures finissent sans réserve vide ; les deux déplacements échouent. Le refus d'une nouvelle tentative pendant la lecture motive le maintien du contexte engagé. |
| `runtime-continuous-03` | Avec les nouvelles tentatives pendant la lecture : deux postures finissent ; les deux déplacements échouent sur les limites de correction des appuis Core. Deux attentes sont observées. |
| `runtime-continuous-cancel-01` | Arrêt confirmé 0,340 s après le début, génération suivante encore en cours. Pose Core, apparence et observation terminale sont identiques à l'état arrêté. Les deux postures suivantes finissent ; le déplacement suivant échoue sur la variation de hauteur VRM. |
| `runtime-continuous-holdout-01` | Autre graine 138124 et cibles `(0 ; 0,75)` puis `(0,35 ; 0,45)` : deux postures finissent, deux déplacements échouent. Corrections VRM demandées de 6,816 cm et 5,078 cm, au-delà des 5 cm conservés. Cinq attentes de suite valide. |

Dans la série d'annulation, le travail Core des blocs réutilisant le texte dure
0,307–0,503 s et la préparation VRM 1,151–1,375 s. Aucune réserve vide n'y est
enregistrée. Sur la série indépendante, les plages montent à 0,404–0,957 s et
1,415–2,010 s : deux secondes d'avance ne suffisent donc pas toujours.
Ces plages sont des observations de petites séries, pas un P95 ni une garantie
de débit. Le premier bloc reste lent : environ 4,4–5,8 s dans la série
d'annulation et 7,0–8,0 s pour les actions démarrées de la série indépendante.
Il faut encore réduire cette attente et qualifier la préparation sous charge.

La capture `.local/exports/promethee-continuous-20260915.webm` dure 45,166 s,
en 1600 × 900 à 30 images/s. Elle rejoue la série 03 en conservant ses temps
d'attente et la dernière observation jusqu'à la suivante ; les poses sources
restent à 20 Hz. Les passages de déplacement, levée et descente des bras ont
été inspectés. Le rendu montre aussi l'arrêt jambes écartées après un échec :
ce n'est pas une démonstration de naturalité ou de conversation.

La suite complète de 439 tests Python passe, avec deux tests ignorés ; les
21 tests ciblés repassent après ajout d'un contrôle du nombre de poses par bloc.
Les nouveaux cas couvrent
historique borné, trous d'observation, contexte futur, cache par action,
génération pendant lecture, cible finale immuable, attente, nouvelles tentatives,
annulation aux différentes étapes et restauration de la même apparence.
Ces tests utilisent des doubles pour l'orchestration ; les séries ci-dessus
constituent les essais du vrai modèle.

La prochaine étape est de traiter les trajectoires et transitions encore
refusées, puis de mesurer une réserve adaptée à toute la chaîne et son
interruption. Le rendu interpolé, la voix réelle, le visage et le téléphone
restent des capacités distinctes à qualifier.

## Recherches du 16 septembre

La [comparaison avec la démo officielle](research/07-official-reference.md)
documente les expériences suivantes : plafond de contexte, conservation des
caractéristiques explicites, commande de vitesse et repos généré, corrections
Core et VRM séparées. Une correction d'ancrage permet aux trois blocs d'un
ancien essai de passer la validation VRM avec les mêmes poses et tolérances.
Le profil de trajectoire améliore le départ brut, mais reste refusé par les
contrôles Core sur les deux graines testées ; il n'est pas activé dans le runtime.

Le contrat de lecture évolue également de 40 poses sur 39 intervalles à une
origine suivie de 40 poses futures. Le test d'orchestration exige désormais six
secondes pour trois blocs préchargés. Ce correctif préserve l'origine Core et
son apparence exacte ; il ne garantit pas que les blocs suivants soient prêts
assez tôt pour éviter toute attente.
