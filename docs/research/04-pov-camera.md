# Caméra POV tenue comme un smartphone — recherche du 15 septembre 2026

## Décision recommandée

Créer un téléphone cinématique avec une caméra liée à sa lentille, une pose de prise et une orientation de poignet explicites. Cela peut réutiliser le contrôleur et le rendu actuels, sans nouveau modèle GPU et sans entraînement RL. Le coût principal est la coordination main–doigts–regard et la continuité du mouvement, pas le calcul du point de vue.

La scène où Ariane s'approche, se présente et manipule la caméra reste un test ponctuel demandé par l'utilisateur. Elle ne doit devenir ni routine automatique ni scénario de vie imposé.

## Ce que le code permet déjà

| Élément inspecté | Capacité présente et limite |
|---|---|
| `src/promethee/spatial.py` | Attachement à une main avec position et rotation locales ; transformation mondiale validée. Aucun contact physique ou doigt simulé. |
| `src/promethee/object_actions.py` | Approche, contact ponctuel et levée de 6 cm ; contrôle conservateur objets/AABB et segments corporels. La prise impose `HAND_ROTATION` et choisit la main accessible la plus proche. |
| `src/promethee/arm_reach.py` | Cible de poignet et `hand_rotation` déjà disponibles ; interpolation SO(3) et smoothstep sur 61 poses par défaut à 20 Hz. Pas de limites articulaires ni de collision des doigts. |
| `src/promethee/avatar_reach.py` | Portée du vrai VRM vérifiée à partir du profil ; ce contrôle ne valide ni fermeture, ni volume de peau, ni limites du poignet. |
| `src/promethee/object_models.py` | Balle et doudou composés d'ellipsoïdes ; points de contact gauche/droite. Ajouter un parallélépipède simple pour le téléphone demande aussi d'adapter son calcul d'encombrement. |
| `web/avatar/objects.js` | Objets rendus directement depuis leurs transformations mondiales observées. Très bonne base pour y placer la caméra. |
| `web/avatar/app.js` et `live.js` | Caméra d'observation avec OrbitControls ; aucun point de vue attaché à un objet. |
| `src/promethee/world.py` | `take` accepte un ID ; `place` une position uniquement. Un seul `holding` global, donc un seul objet porté actuellement. |

Inspection du VRM local : tous les 30 os de doigts standards sont présents, trois par doigt et par main. Le squelette Core de 27 articulations ne possède pas ces doigts : ils doivent appartenir à une couche d'apparence contrôlée et persistée, plutôt qu'être supposés animés par ARDY. Les préparations d'apparence et leur restauration devront intégrer cette nouvelle information.

## Point de vue : solution simple et exacte

Définir dans le modèle de téléphone un repère de lentille, en mètres, indépendamment du repère de prise. Le point optique se trouve sur la surface externe, orienté du bon côté. La règle est :

`T_monde_camera = T_monde_telephone × T_telephone_lentille`

Le téléphone utilise déjà la transformation mondiale issue de la main. On peut faire de la caméra un enfant du nœud de l'objet, ou calculer la matrice mondiale directement. Ne pas réattacher aussi l'objet à la main VRM : cela appliquerait deux fois la relation que le backend fournit déjà. Three.js expose séparément les transformations locales et mondiales ; `attach` conserve le monde mais ne supporte pas les parents à échelle non uniforme. [Object3D](https://threejs.org/docs/pages/Object3D.html).

Three.js regarde suivant l'axe local `-Z` de la caméra. Il faut tester le repère de la lentille avec un motif asymétrique et non supposer qu'il correspond à l'axe avant du téléphone. [Camera](https://threejs.org/docs/pages/Camera.html).

Prévoir deux vues : observation libre pour le diagnostic, lentille du téléphone pour le POV. Changer la vue est un réglage d'affichage ; bouger le téléphone est une action corporelle. L'agent n'a pas besoin de modifier directement les coordonnées de la caméra. La scène peut commencer dans la vue du téléphone posé, conserver exactement cette vue pendant l'approche puis pendant sa prise : pas de coupe nécessaire pour masquer un saut.

Choisir un FOV fixe et documenté, puis ajuster la pose du bras pour cadrer le visage ; ne pas faire zoomer la caméra automatiquement afin de cacher une mauvaise portée. Première plage à essayer : FOV vertical 55–70°, format portrait 9:16, lentille à quelques dizaines de centimètres du visage. Ce sont des paramètres de test, pas des propriétés universelles d'un smartphone. `PerspectiveCamera` utilise un FOV vertical, un aspect largeur/hauteur et des plans near/far ; toute modification exige `updateProjectionMatrix()`. [PerspectiveCamera](https://threejs.org/docs/pages/PerspectiveCamera.html).

Pour la petite pièce, un plan proche de l'ordre de 5–10 mm et un plan lointain limité à la pièce constituent un point de départ à mesurer. Le nez, la main, les cheveux et le téléphone doivent rester réellement à l'extérieur de la lentille. Ne pas cacher la tête ou les bras pour rendre le selfie propre. Le système `VRMFirstPerson` sert aux couches de visibilité de la vue depuis l'avatar ; notre lentille extérieure doit voir le visage complet. [VRMFirstPerson](https://pixiv.github.io/three-vrm/docs/classes/three-vrm.VRMFirstPerson.html).

## Prise et mouvement : le vrai chantier

Un point de contact ne suffit plus en gros plan. Ajouter un petit profil de prise propre au téléphone : paume, orientation, décalage de poignet, pose des doigts, espace libre devant la lentille. Commencer par une prise à une main, téléphone vertical ; varier ensuite main et orientation. Le pouce ne doit pas traverser l'écran, ni les doigts la coque. Les doigts se ferment pendant la fin de l'approche, avant la levée, puis s'ouvrent lors d'un dépôt stable.

Réutiliser l'IK analytique existante pour le bras. Le solveur Three.js CCD est une autre possibilité et fournit des bornes de rotation, mais il travaille sur les indices d'un `SkinnedMesh` et ajouterait un second solveur à réconcilier avec Core et le VRM ; il ne résout pas la physique de contact. Il n'est pas nécessaire pour la première version. [CCDIKSolver](https://threejs.org/docs/pages/CCDIKSolver.html).

Ajouter une intention de repositionnement de l'objet tenu, par exemple `reposition_held` avec position, orientation et durée bornées. Le contrôleur résout le poignet depuis l'attachement, vérifie toute la trajectoire puis conserve la prise. Ce nom est une proposition, pas une API existante. Un futur mode de cadrage pourrait convertir « cadre mon visage » en cible optique, mais ne doit pas être ajouté avant que la commande géométrique fonctionne.

Le regard utilise la position mondiale de la lentille observée, pas celle de la caméra d'observation. La tête et le bras sont composés ensemble pour éviter de tourner la tête à la poursuite d'une caméra elle-même asservie sans limite au visage. Les yeux peuvent anticiper, mais une main occupée ne doit pas être réaffectée à un geste de parole.

L'effet fluide doit venir de trajectoires continues et de transitions à vitesse maîtrisée. Échantillonner corps, main, doigts, objet et caméra sur le même instant de présentation ; interpoler chacun indépendamment provoquerait un décollage visible de la prise. Le mouvement 20 Hz actuel devient particulièrement visible en POV. Le travail du blocage « continuité » est donc une dépendance directe.

Commencer sans faux tremblement et sans stabilisation qui masque les erreurs. Si un mode de stabilisation optique est ensuite ajouté, il conserve séparément la pose physique et le cadrage stabilisé, avec une amplitude limitée. Une vue de diagnostic non stabilisée reste disponible.

## Contrats et modifications ciblées proposées

1. `catalog.py`, `object_models.py`, `web/avatar/objects.js` : un asset téléphone original simple ; géométrie de coque et lentille, volume de collision cohérent, profil de prise versionné. Aucun système générique d'assets n'est nécessaire.
2. `world.py`, `object_actions.py`, `kinematic.py` : action d'orientation/repositionnement du téléphone tenu ; préconditions, cible hors de portée, rotation impossible, annulation et progression. Garder `take`/`place` compatibles ; la sélection de main explicite peut être un champ optionnel validé, pas un changement silencieux des anciennes commandes.
3. Profil d'apparence et préparation VRM : poses de doigts liées au profil de prise, articulations bornées, version et empreinte de l'asset. Étendre explicitement schéma, validation et checkpoints si la pose nouvelle doit survivre à un redémarrage.
4. Petit module `web/avatar/camera.js` proposé : dérivation du repère optique, choix de vue, réglage projection et instrumentation. Il lit les observations et n'atteste aucune réussite corporelle.
5. Retarget et préparation : même pose de poignet, mêmes horodatages et mêmes interpolations pour objet et rendu. Les profils anatomiques restent dans le contrôleur ; pas de correction visuelle invisible de l'objet.

Ne pas élargir immédiatement `holding` en inventaire à deux mains : le modèle actuel mono-objet suffit à cette capacité. Une main peut porter le téléphone pendant que l'autre fait un geste libre, mais une deuxième prise reste refusée tant que le contrat mono-objet existe.

## Annulation, reprise et erreurs

Une annulation avant contact ne crée aucun attachement. Après contact, elle conserve téléphone et doigts dans la prise observée et freine le déplacement jusqu'à une pose admissible. Une annulation de parole n'est pas un dépôt du téléphone. Au redémarrage, restaurer la même relation main–objet et la pose des doigts ; ne pas lancer automatiquement un nouveau cadrage ni rejouer la prise.

Pendant la préparation d'une trajectoire, une modification du monde invalide celle-ci. Si le flux d'observations se coupe, geler ou signaler l'indisponibilité de la vue ; ne pas poursuivre un téléphone animé sans observation et ne pas annoncer la fin de l'action. Un dépôt doit avoir une surface/support défini ; le système actuel laisse les objets libres immobiles, même en l'air, ce qui ne constitue pas un dépôt physique.

## Option physique : utile plus tard, distincte

Une version avec gravité peut employer un corps rigide de téléphone et des colliders des mains. Rapier distingue corps dynamiques et cinématiques et propose des joints fixes. Un joint fixe impose une liaison ; même avec une gravité simulée, cela demeure une prise assistée et non une réussite issue des forces des doigts. [Corps rigides](https://rapier.rs/docs/user_guides/javascript/rigid_bodies/), [joints](https://rapier.rs/docs/user_guides/javascript/joints/).

Une vraie prise demande géométrie de doigts, friction, articulations, forces, contacts, glissement et cas de chute. Le moteur du contrôleur doit faire autorité sur ces résultats. Ajouter Rapier seulement dans le navigateur créerait une seconde vérité incompatible avec les observations Python ; une intégration physique doit être conçue au niveau du contrôleur. Aucun nouveau moteur n'est recommandé pour le jalon POV immédiat.

Le budget GPU déjà serré de la machine motive aussi une première solution géométrique légère. Deux caméras n'exigent pas deux rendus complets simultanés : une vue principale suffit ; une petite vue diagnostic peut être activée ponctuellement. Un écran de téléphone affichant lui-même sa caméra n'est pas requis et éviterait une passe supplémentaire et une récursion de rendu.

## Preuves attendues

- Trajectoires variables : deux mains, plusieurs hauteurs/directions de téléphone, rotation portrait/paysage, cible atteignable et cible impossible. La pose de départ n'est pas toujours la meilleure prise.
- Exactitude : caméra dérivée de l'objet à chaque image ; test des axes avec motif asymétrique ; absence de saut à l'attachement et au dépôt. Cible de précision de projet : variation parasite inférieure à 2 mm et 1° à ces transitions.
- Main visible : contacts paume/doigts dans un seuil visuel choisi, aucune pénétration visible de coque, aucun doigt devant la lentille involontairement ; contrôle en vue observateur et en POV sur le même essai.
- Continuité : mesurer vitesse/accélération angulaire de la lentille, temps de frame et pauses ; aucune image qui saute ou gel à une transition. Comparer à une capture réelle de manipulation de téléphone comme référence visuelle, sans copier une trajectoire unique dans l'agent.
- Invariants : arrêt avant/après prise, refus si occupé, perte de connexion et redémarrage gardent une relation cohérente. Une commande refusée ne déplace ni lentille ni objet.
- Validation utilisateur : séquence continue de 30–60 secondes avec approche, prise, variation de cadrage, parole et interruption. Conserver aussi les vues de diagnostic montrant les doigts et le corps ; la qualité ne se juge pas sur les seules coordonnées de caméra.

## Effort indicatif

Caméra liée à un téléphone déjà placé : 1–2 jours. Prise à une main, orientation, pose de doigts et validations : environ 4–8 jours supplémentaires. Continuité à 60 images/s, arrêt/reprise et revue de plusieurs configurations : 3–5 jours, en dépendance du travail corporel. Total approximatif 1–3 semaines pour un POV cinématique crédible selon la qualité du contrôle actuel, sans promesse de marche ou de voix naturelle. La prise physique est un chantier séparé de plusieurs semaines ou davantage, à estimer après un premier essai.

Recherche et inspection uniquement : aucune installation, aucun entraînement, aucune modification du code de production. Ces capacités restent proposées, elles n'ont pas été livrées par cette recherche.
