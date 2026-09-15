# Contrôleur cinématique — qualification T07 en cours

Le runtime reçoit maintenant des poses réellement générées par ARDY, avec un
processus moteur séparé pour Python 3.11/WSL. La boucle de lecture tourne à
20 Hz ; elle persiste un point observé toutes les 250 ms et le résultat terminal.
Le modèle ne possède aucune connexion SQLite. Les blocs complets de six secondes
sont générés avant lecture : il ne s'agit pas encore d'une génération continue.

## Lancer et piloter

Installer les deux environnements et démarrer l'encodeur selon
[l'essai moteur](../experiments/motion/README.md). Installer le rendu optionnel
avec `uv sync --locked --extra viewer`. Exemple Windows/WSL effectivement exécuté :

```sh
python -m promethee.cli --data-dir .local/ma-session run --ardy-python /root/.local/share/promethee/ardy-env/bin/python --checkpoint-root /root/.local/share/promethee/checkpoints --wsl Ubuntu-22.04 --port 2337
```

Ouvrir `http://127.0.0.1:2337`. Une session neuve part sans objet. Les boutons
soumettent une intention avec la révision courante ; ils permettent un déplacement,
une demande de posture et un arrêt. Le corps affiché est encore le squelette Core.
Les demandes de posture sont `standing` et `arms_raised`, sans préférence ni routine.
Les essais de posture peuvent échouer ; leur résultat est contrôlé sur les poignets,
la tête et le tronc obtenus, pas sur le texte demandé.

Les mêmes opérations sont disponibles sans les boutons :

```sh
python -m promethee.cli --data-dir .local/ma-session world
python -m promethee.cli --data-dir .local/ma-session submit --request-id mon-mouvement --expected-revision 1 --file action.json
python -m promethee.cli --data-dir .local/ma-session execution --request-id mon-mouvement
python -m promethee.cli --data-dir .local/ma-session cancel --request-id mon-mouvement
```

La révision `1` ci-dessus doit être remplacée par celle qui vient d'être lue.
Un fichier peut contenir `{"kind":"move","args":{"position":[0.5,0.2]}}` ou
`{"kind":"posture","args":{"name":"arms_raised"}}`. Le code de sortie d'une
soumission acceptée ne signifie pas que le mouvement est terminé. Relire son état.
Les requêtes au-delà de deux mètres échouent explicitement avant génération :
leur durée et leur trajectoire ne sont pas encore qualifiées.

## Arrêt et reprise

L'arrêt fige la dernière pose effectivement lue par le corps cinématique. Une
génération déjà lancée peut finir en arrière-plan, mais son résultat annulé est
ignoré et ne sera jamais joué. Ce gel ne garantit aucun équilibre physique.
Une autre demande peut être acceptée après confirmation de l'arrêt ; son envoi
attend que l'unique processus moteur soit libre.

Fermer le pilote interrompt toute demande non terminale et rend le corps non
confirmé. Après un arrêt brutal, l'expiration du bail produit le même effet.
Relancer exactement la même commande restaure le corps virtuel à sa dernière pose
persistée et la réconcilie ; aucune ancienne intention n'est réémise. La perte
maximale normale correspond au point de sauvegarde de 250 ms, et non à une
observation d'un corps physique extérieur. Une nouvelle tentative utilise un nouvel ID.

Les bases v3 requièrent la migration explicite avec sauvegarde décrite dans
[les contrats](contracts.md). Les bases `fixture` et `legacy` sont refusées par
`run`. Les dossiers `controller-check-*` et `manual-session-*` utilisés ici
sont exclusivement des essais du pilote réel ; ils n'alimenteront aucun coffre
ni profil Hermes personnel, malgré leur origine technique `session`.

## Résultats conservés localement

Environnements et révisions identiques à T02. Aucun résultat de test synthétique
n'est compté comme une réussite motrice.

| Essai réel | Observation |
|---|---|
| `.local/worker-check-01`, graine 501 | Premier raccord Windows → WSL : 40 poses générées, 5,899 s incluant le texte, erreur finale 4,33 mm |
| `.local/controller-check-01`, graines 601–603 | Initialisation puis déplacement vers `[0.7,0.3]` terminé à `[0.707563,0.300402]` ; la posture suivante est correctement marquée `failed`, bras non maintenus en hauteur |
| `.local/manual-session-01`, graine initiale 701 | Rendu réel observé dans le navigateur ; déplacement demandé par les boutons vers `[1,-0.5]`, terminé à `[1.002616,-0.513364]` |
| `real-cancel-playback-01` dans ce même dossier | Annulation après progression visible ; 47,38 ms entre demande et lecture de l'accusé, arrêt à `[0.937149,-0.489047]` ; pose identique deux secondes plus tard |
| `.local/motion-transition-03`, graine 401 | Déplacement depuis une pose antérieure, discontinuité initiale maximale des articulations 0,000000246 m après post-traitement |
| `.local/motion-transition-04`, graine 402 | Posture bras levés atteinte ; poignets respectivement 0,332 et 0,316 m au-dessus de la tête à la fin |

`experiments/motion/transition_trial.py` conserve la configuration, le résultat
brut et le résultat post-traité. `experiments/motion/measure_contacts.py` mesure
le véritable maillage Core chargé depuis ARDY :

| Mesure | Transition 03 | Transition 04 |
|---|---:|---:|
| Pénétration maximale du maillage sous le sol | 25,92 mm | 15,29 mm |
| Images avec pénétration > 10 mm | 76 / 120 | 120 / 120 |
| Vitesse des pieds en contact, percentile 95 | 0,0314 m/s | 0,0264 m/s |
| Vitesse maximale des pieds en contact | 0,1627 m/s | 0,1336 m/s |

Le contact utilisé ici est la sortie prédite par ARDY (> 0,5 dans deux images
consécutives), pas un capteur de collision. La pénétration utilise les sommets
du maillage et révèle un défaut que la hauteur positive des articulations des
pieds ne montrait pas. Résultat détaillé : `.local/transition-contacts-01.json`.

## Deuxième série : contraintes de posture et raccord progressif

Le contrôleur courant ajoute une contrainte finale calculée sur le vrai squelette
pour les deux postures. Elle conserve la configuration observée du tronc et des
jambes et modifie les bras. La sortie brute ARDY reste enregistrée. Le raccord
à la pose courante corrige progressivement les rotations locales et la racine
pendant les 16 premières images, avec une décroissance cubique ; la cinématique
directe préserve les longueurs des os. Ce traitement n'est pas une animation de
remplacement. Le post-traitement C++ initial reste dans les expériences de T02,
mais n'est plus appliqué par le pilote courant : il aggravait certaines transitions.

Une correction verticale du corps entier évite que le maillage Core traverse
le sol. Elle conserve les coordonnées XZ et les rotations ; une enveloppe
anticipée limite ses variations à 15 mm par image, avec une hauteur maximale
de 5 cm. Au-delà, le mouvement est refusé. Elle ne résout ni l'équilibre, ni
les collisions avec objets, ni le glissement horizontal.

Les critères numériques de lecture sont conservés dans
[`runtime-criteria.json`](../experiments/motion/runtime-criteria.json). Le pilote
refuse aussi un pas articulaire > 30 cm par image et un glissement des articulations
de pied déclarées en contact > 0,2 m/s au maximum ou > 0,05 m/s au percentile 95.
Ces critères n'ont pas été élargis après les rejets ci-dessous.

| Série | Postures terminées | Déplacements terminés | Rejets observés |
|---|---:|---:|---|
| `runtime-holdout-01`, graines 901–905, ancien post-traitement | 1 / 2 | 0 / 2 | Glissement, pas articulaire, correction verticale trop brusque |
| `runtime-holdout-02`, graines 1001–1005, raccord progressif | 2 / 2 | 1 / 2 | Glissement au premier déplacement |
| `runtime-holdout-03`, graines 1101–1105 | 2 / 2 | 0 / 2 | Glissement aux deux déplacements |
| `runtime-holdout-04`, graines 1201–1205 | 2 / 2 | 0 / 2 | Correction verticale > 5 cm, puis glissement |

Un rejet de trajectoire intervient avant sa lecture et conserve la pose courante.
Les sources, paramètres, requêtes, graines, critères et résultats de chaque série
sont locaux. `qualify_runtime.py` reproduit la boucle réelle. La première série
a ensuite servi au diagnostic du raccord ; les séries 02–04 ont servi à vérifier
ce changement. Elles ne seront pas réutilisées comme cas indépendants pour une
correction conçue à partir de leurs défauts.

Les mesures indépendantes du maillage des séries 02 et 03 trouvent une pénétration
résiduelle inférieure à 10⁻⁸ m, due à l'arrondi numérique. Les contacts géométriques
ont aussi été mesurés pour diagnostic : même sommet de pied à moins de 5 mm du sol
dans deux images consécutives, avec un poids de peau vers les os du pied > 0,5.
Ce diagnostic montre que vitesse d'une articulation et glissement de la surface
au sol diffèrent ; il ne remplace pas encore le critère de rejet. Certains pics
géométriques restent excessifs, et les déplacements ne sont donc pas qualifiés
comme fiables dans toutes les directions.

Les vidéos MP4 de 120 poses sont produites à 20 Hz par
[`render_mesh_video.py`](../experiments/motion/render_mesh_video.py), à partir du
maillage et des transformations enregistrés, sans lissage ni changement de durée.
Les images 0, 60 et 119 sont également conservées. Dossiers :
`video-ground-calibration-01`, `video-posture-calibration-02`,
`video-runtime-holdout-02-move`, `video-runtime-diagnostic-03` sous `.local/`.
Le rendu logiciel est orthographique et colore en rouge les faces sous le sol.
Des images du rendu et une lecture vidéo de calibration ont été inspectées ;
le lecteur multi-vidéos du navigateur intégré a planté pendant la revue suivante.
La revue visuelle complète de cette seconde série reste à achever.

La panne réelle du processus ARDY a aussi été provoquée pendant une demande :
`real-worker-loss-01` devient `interrupted`, avec le corps non confirmé et sa pose
préservée. Au redémarrage, cette même pose est réconciliée sans génération ni
réémission de l'ancienne demande. Mesures dans
`.local/manual-session-01/crash-measurement.json` et `restart-measurement.json`.

## Troisième série : appuis des jambes et contrôle du maillage

`ardy_contacts.py` conserve un point d'appui par talon et orteil tant que le
contact prédit reste actif. Une résolution géométrique des deux segments de
jambe ajuste les rotations sans allonger les os ni changer la trajectoire XZ
du bassin. Une cible hors de portée est projetée dans l'espace atteignable ;
son écart est mesuré. Le décalage se dissipe en huit images pendant la phase
sans appui. Le tronc, les bras et le mouvement de balancement viennent d'ARDY.
Ce traitement reste cinématique. Il précède la correction verticale du maillage
et ne s'applique qu'aux déplacements, pas aux postures ni à l'initialisation.

Les scripts `contact_order_trial.py` et `foot_anchor_trial.py` gardent les essais
comparatifs. Replacer le correcteur C++ officiel après le raccord progressif,
avec la racine finale ou toute sa trajectoire contrainte, augmente le maximum
de glissement à environ 0,700 m/s sur le cas étudié. Le correcteur des jambes
ramène ce maximum prédit à 0,067 m/s sur ce même cas. Les séries 02–04 servent
désormais de calibration, sans être recomptées comme vérification indépendante.
Un de leurs cas reste impossible à ramener dans l'enveloppe verticale de 5 cm.

Deux séries nouvelles, 05 (graines 1401–1405) et 06 (1501–1505), ont terminé
leurs quatre actions avec les anciens contrôles : quatre déplacements et quatre
postures au total. Erreurs finales des déplacements : 10 à 22 mm. Cependant,
le diagnostic indépendant des sommets de semelle contredit ce succès :

| Déplacement | Maximum prédit (m/s) | Maximum du maillage (m/s) | P95 du maillage (m/s) |
|---|---:|---:|---:|
| Série 05, premier | 0,127 | 0,215 | 0,0157 |
| Série 05, second | 0,042 | 3,439 | 0,2918 |
| Série 06, premier | 0,007 | 1,229 | 0,0315 |
| Série 06, second | 0,048 | 1,813 | 0,0216 |

La pénétration résiduelle est inférieure à 4 × 10⁻⁹ m. Elle ne suffit pas à
prouver un appui correct. La vidéo `video-runtime-holdout-05/motion.mp4` montre
aussi un tronc fortement penché sur le second déplacement ; la marche ne peut
donc pas être qualifiée de naturelle sur la base de ces chiffres. Le lecteur
vidéo simple fonctionne, contrairement au précédent lecteur multi-vidéos.

La version 2 des critères ajoute un rejet conservateur sur les sommets de pied
portant plus de 50 % de poids de peau vers les quatre os de pied. Le même sommet
doit être à moins de 5 mm du sol dans deux images successives. Les limites sont
0,2 m/s au maximum et 0,05 m/s au percentile 95 ; l'absence de paire de contact
vérifiable est également refusée. Les anciens seuils restent inchangés. Les
mesures sont enregistrées dans `JOB-contacts.json` même si la trajectoire échoue.
Ce critère géométrique ne certifie pas l'équilibre physique.

La série 07 (graines 1601–1605), réservée après cette modification, termine les
deux postures et refuse les deux déplacements avant lecture : maxima du maillage
0,325 et 1,033 m/s. Le runtime conserve la position observée précédente. Les
réussites historiques 05–06 ne sont pas réécrites ; elles attestent les contrôles
de cette ancienne version et restent des données de qualification exclues de
toute mémoire d'agent. Les neuf tests CPU de géométrie couvrent les rotations,
les limites de portée, les segments dégénérés et le rejet d'une semelle glissante
ou sans contact vérifiable. Les essais GPU restent nécessaires pour la marche.

## Limites empêchant de clôturer T07

Trois corrections supplémentaires ont été essayées puis écartées du pilote :

- Une contrainte finale du corps entier, obtenue en translatant la pose observée
  à la destination. La série `runtime-holdout-08` (1701–1705) conserve deux postures
  terminées mais refuse les deux déplacements : maxima du maillage 2,261 et
  0,913 m/s. Les inclinaisons finales tête/bassin sont 2,21° et 2,81° ; une posture
  finale plus droite ne résout donc pas le glissement pendant le trajet.
- La même contrainte, avec une durée calculée à 0,6 m/s plus 0,4 s d'arrêt,
  arrondie aux blocs de quatre poses et bornée à au moins 40 poses. L'essai
  `runtime-duration-calibration-01` reprend les mêmes graines et cibles : les
  deux déplacements restent refusés (maxima 0,350 et 1,486 m/s). Le premier cas
  donne un P95 de 0,079 m/s, lui aussi au-delà du seuil. Les postures restent
  inchangées et terminées. Cette comparaison n'est pas une nouvelle vérification
  indépendante après calibration.
- Une union des contacts prédits et des pieds dont le maillage approche le sol,
  essayée hors pilote via `foot_anchor_trial.py --from-raw --geometry-support`.
  `geometry-support-calibration-01` dépasse l'enveloppe verticale de 5 cm ; le
  second cas atteint un maximum de glissement de 2,303 m/s malgré un P95 de
  0,020 m/s. Verrouiller tout le pied à partir de cette proximité ne suffit pas.

Le [patch de ces deux premières variantes](../experiments/motion/arrival-duration.patch)
est conservé pour reproduction depuis le code de base `22b51e4`. Vérifier son
application avec `git apply --unidiff-zero --check` dans un checkout de recherche,
puis appliquer avec `git apply --unidiff-zero`
et lancer `qualify_runtime.py` avec les paramètres ci-dessus. Pour isoler la
première variante, appliquer uniquement la partie concernant `ardy_worker.py`.
Ce patch n'est pas appliqué au pilote livré. Les critères restent en version 2.

Le diagnostic [diagnose_sole_sliding.py](../experiments/motion/diagnose_sole_sliding.py)
localise les sommets et images responsables. Dans le premier déplacement de la
série 07, le pic de 0,325 m/s se situe aux images 105–106, sur une semelle gauche
à 3–5 mm du sol dont les deux contacts prédits sont faux. Dans la série 08,
le pic de 2,261 m/s concerne la semelle droite aux images 69–70, à 0–2 mm du
sol et également déclarée sans contact. Il ne s'agit donc pas uniquement d'une
erreur de rotation à l'arrivée. Les JSON détaillés restent dans ces dossiers.

La vidéo `video-duration-calibration-01` conserve la séquence raccourcie du
second déplacement, sans correction du rendu. Sa lecture a été lancée dans le
navigateur ; les poses de début, milieu et fin ont été inspectées. Aucun de ces essais ne justifie
de déclarer la marche qualifiée ni de lancer un entraînement complet.

Les seuils incluent une erreur de cible ≤ 5 cm, une discontinuité initiale ≤ 2 cm,
un saut de racine ≤ 12 cm par image, une racine dans la pièce et des rotations
finies et orthonormales. Le nombre de déplacements refusés reste trop élevé.
La fiabilité directionnelle, la revue complète des vidéos et la correction des
pics de glissement du maillage restent à résoudre. Le nouveau rejet les expose
mais ne constitue pas une correction de la marche.

L'[avatar anime](assets/pixiv-vrm-sample.md) suit les mouvements enregistrés dans
une vue séparée en lecture seule. Les interactions corporelles avec objets,
la conversation Hermes/Astra, la mémoire d'agent et la voix restent à livrer.
