# Marche, appuis et équilibre : solutions pour Promethee

Recherche du 15 septembre 2026. Lecture du code et des preuves locales, recherche documentaire primaire ; aucune nouvelle qualification, installation ou modification du runtime. Les critères et durées ci-dessous sont des propositions, pas des résultats acquis.

## Diagnostic vérifié

Le problème n'est pas l'absence de modèle de mouvement. ARDY propose déjà la démarche ; Promethee doit ensuite la rendre compatible avec le sol, les proportions du VRM et la pose précédemment affichée.

- Le dernier essai indépendant termine deux postures et un déplacement à environ 9 mm de sa cible. Un autre déplacement est refusé par la limite de correction verticale. Quatre actions ne permettent pas d'estimer une fiabilité générale. Les trois séquences acceptées ont un contact géométrique par pose et une discontinuité initiale inférieure à 0,02 mm. [Audit local](../completion-audit.md), [historique des essais](../live-avatar.md).
- `stabilize_contacts` et `project_support` corrigent les jambes par cinématique inverse. Ce ne sont pas des solveurs de forces. Le bassin peut être abaissé jusqu'à 5 cm ; la projection échoue au-delà. Le prédicteur de contacts est aussi un point de refus. [Calculs Core](../../src/promethee/ardy_contacts.py#L55).
- Le VRM subit une seconde adaptation, avec ses propres longueurs de jambes et surfaces de chaussures. Le calcul reprend les appuis précédents : cela améliore la continuité mais peut aussi conserver une pose aux jambes croisées. L'enchaînement des corrections Core puis VRM est une cause plausible d'incompatibilité à mesurer, pas encore une cause unique démontrée. [Retargeting](../../web/avatar/retarget.js#L77), [appuis VRM](../../web/avatar/foot-planting-trial.js#L17).
- Les collisions objet/corps utilisent des volumes conservateurs. Le contrôle ne compare pas les jambes entre elles ; il n'établit ni absence d'auto-intersection du maillage ni équilibre dynamique. [Volumes de contrôle](../../src/promethee/object_actions.py#L47).
- Les relances ARDY ne résolvent que certains défauts de proposition et peuvent augmenter l'attente. Elles ne remplacent ni un contrôleur continu ni une preuve physique. [Relances](../../src/promethee/kinematic.py#L310).

## Ce qui est réellement disponible

ARDY reste officiellement un générateur cinématique autorégressif, avec contraintes de trajectoire et d'articulations. Des modèles Core à horizons 40 et 8 sont publiés ; la variante SOMA est encore annoncée à venir dans le README consulté. Changer l'horizon peut modifier la réactivité, mais n'ajoute pas de forces, d'équilibre ou de collisions. Code Apache-2.0 ; poids sous licence NVIDIA distincte. [Dépôt officiel](https://github.com/nv-tlabs/ardy/blob/main/README.md), [poids Core](https://huggingface.co/nvidia/ARDY-Core-RP-20FPS-Horizon40).

NVIDIA présente ARDY associé à SONIC pour le suivi physique. Les poids SONIC publics consultés sont toutefois des contrôleurs Unitree G1 à 29 actions : ils ne pilotent pas directement le squelette Core27 ou un VRM. Code Apache-2.0 et poids NVIDIA Open Model License. Leurs références futures et leur normalisation sont propres à chaque variante. [Présentation ARDY](https://research.nvidia.com/labs/sil/projects/ardy/), [fiche SONIC](https://huggingface.co/nvidia/GEAR-SONIC), [licence](https://huggingface.co/nvidia/GEAR-SONIC/blob/6abbfb72ba764eaae06714a4a5cea6461fb7f3f8/LICENSE).

## Trois options applicables

| Option | Ce qu'elle apporte | Ce qu'elle ne garantit pas | Coût d'intégration estimé |
|---|---|---|---|
| A. Conserver ARDY et corriger son raccord géométrique | Réutilise le code, les poses, le VRM et les commandes existantes ; permet de localiser les refus puis d'améliorer les propositions | Équilibre physique, robustesse universelle, détails des mains | Diagnostic comparatif 2–3 jours ; corrections ciblées 1–2 semaines si cause localisée |
| B. Bibliothèque de locomotion et sélection continue de poses | Marche, démarrage, freinage et virages plus prévisibles ; commandes de vitesse/direction évaluées en continu ; pas d'encodage de texte pour chaque pas | Diversité hors bibliothèque, physique complète, gestes nouveaux | Prototype 2–4 semaines, conditionné par des animations adaptées et autorisées |
| C. Générateur puis contrôleur physique préentraîné | Appuis issus du simulateur, masses, inerties et réaction aux perturbations ; base cohérente pour interactions physiques | Adaptation automatique au VRM, réussite de tout mouvement généré, absence d'entraînement ultérieur | Essai isolé 1–2 semaines ; intégration réaliste 4–8 semaines ou davantage |

Ces fourchettes sont des estimations d'ingénierie à une personne connaissant l'animation, sans engagement de résultat. Pas de prix cloud estimé sans benchmark et choix de fournisseur.

### A — Une amélioration bornée de l'existant

Comparer sur les mêmes demandes et graines : sortie ARDY brute, correction Core, retarget VRM seul, puis correction VRM. Mesurer à chaque étape portée des jambes, hauteur, glissement, intersections et pose de départ. L'objectif est de trouver l'étape qui dégrade un mouvement acceptable, avant d'assouplir les seuils.

Ajouter des volumes de cuisses/mollets calculés pour le VRM et vérifier leurs distances pendant toute la trajectoire. Une intersection doit déclencher un refus ou une nouvelle planification ; la masquer par le cadrage n'est pas une solution. Pour améliorer la proposition, fournir explicitement direction, vitesse et trajectoire réalisable plutôt qu'un point final isolé. Garder une limitation des corrections, sans monter arbitrairement le plafond de 5 cm.

Cette option peut améliorer la marche visible, mais conservera une locomotion animée géométriquement. Il ne faut pas l'appeler équilibre physique.

### B — Le chemin le plus prévisible vers une marche visuellement convaincante

L'agent choisit une destination, une orientation et une vitesse. Un contrôleur de locomotion cherche une pose compatible avec la trajectoire future, l'appui et la vitesse actuels. Cela donne des comportements composables ; aucune présentation ni routine n'a besoin d'être inscrite dans sa personnalité.

La référence Epic inclut plus de 500 animations, un personnage et un système de Motion Matching, avec retargeting et transitions. Son intégration complète impose un passage à Unreal. Sa fiche Fab ne permet pas ici de conclure aux droits pour notre usage : le champ licence est vide et un indicateur « Allows usage with AI: No » apparaît. Ce n'est pas une autorisation de transformer les animations en données d'entraînement. [Projet officiel](https://www.unrealengine.com/blog/game-animation-sample), [fiche Fab](https://www.fab.com/listings/880e319a-a59e-4ed2-b268-b32dac7fa016).

Pour rester dans Three.js, l'implémentation de recherche de poses de Daniel Holden est une référence technique MIT avec démonstration web. Sa base de mouvements est annoncée séparément CC BY-NC-ND : ne pas la confondre avec la licence du code. Il faut une bibliothèque propre, acquise avec des droits adaptés, ou constituée de sorties dont la provenance autorise cet usage. L'approche peut commencer avec des fondus et une base courte avant un moteur de recherche de poses complet. [Code et licences](https://github.com/orangeduck/Motion-Matching).

### C — La voie physique ambitieuse

Le point de départ le plus adapté est le contrôleur **SOMA BONES-SEED** de ProtoMotions, destiné à un humanoïde numérique. Sa fiche fournit `last_lab.ckpt`, suit des cibles futures et produit 66 actions pour le corps SOMA à 23 segments. Il est qualifié pour IsaacLab ; son ancien export ONNX correspond à un autre checkpoint et ne doit pas être substitué. Le modèle ne génère pas lui-même les intentions ou mouvements de référence. [Fiche exacte](https://github.com/NVlabs/ProtoMotions/blob/main/data/pretrained_models/motion_tracker/soma-bones/MODEL_CARD.md).

Il faut d'abord reproduire l'exemple officiel sur son corps d'origine, puis adapter les références Core vers SOMA, et enfin la pose simulée vers le VRM. La pose observée dans le simulateur doit devenir l'autorité du monde. Un VRM visuellement très différent du corps simulé peut encore traverser le sol : le résultat physique du proxy ne dispense pas de contrôler le rendu. Les politiques humanoïdes numériques ne sont pas annoncées transférables arbitrairement entre simulateurs. [Matrice de disponibilité](https://github.com/NVlabs/ProtoMotions/blob/main/docs/source/getting_started/pretrained_models.rst).

ProtoMotions déclare Apache-2.0 pour le dépôt et distingue les notices de composants et assets. Les fiches consultées ne donnent pas une nouvelle licence indépendante pour chaque checkpoint : conserver les licences exactes des fichiers choisis, sans assimiler tout le corpus à Apache. SOMA-X est Apache-2.0 avec dépendances tierces distinctes ; BONES-SEED possède sa propre licence et demande une acceptation d'accès. [ProtoMotions](https://github.com/NVlabs/ProtoMotions), [SOMA-X](https://github.com/NVlabs/SOMA-X), [BONES-SEED](https://huggingface.co/datasets/bones-studio/seed).

La machine vérifiée possède une RTX 4080 16 Go et environ 32 Go RAM. Elle mérite un essai à un seul personnage ; cela n'atteste pas un entraînement massif ni l'exécution simultanée avec l'encodeur ARDY, mesuré localement à 14,58 Gio de mémoire GPU. Les exigences Isaac Sim indiquent de prévoir davantage de RAM/VRAM pour l'entraînement Isaac Lab. [Mesure locale](../decisions/001-motion-stack.md), [exigences NVIDIA](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/requirements.html).

## Recommandation

Effectuer le diagnostic A sur une durée courte, puis décider avec les images et les mesures. Si une correction locale ne donne pas une marche fiable, adopter B pour le socle de locomotion visible et garder ARDY comme générateur de variantes ou de gestes. Ouvrir C comme essai physique séparé ; ne pas bloquer toute expression et la voix sur une campagne RL.

Il n'est pas nécessaire d'entraîner un humanoïde à partir de zéro pour obtenir une première présence convaincante. En revanche, si l'objectif devient la réaction physique crédible aux meubles, poussées et charges, la voie C sera structurante.

## Acceptation proposée, à figer avant les essais

1. Batterie réservée de 100 déplacements sur sol plat : distances 0,3–2 m dans la limite du contrôleur actuel, différents caps initiaux, virages, arrêt, reprise et destination modifiée. Étendre ensuite jusqu'à 3 m seulement dans une qualification séparée de cette nouvelle portée. Séparer calibration et mesure ; publier tous les refus.
2. Objectif initial proposé : au moins 95 % de demandes terminées, erreur finale inférieure à 5 cm ; aucune intersection persistante entre jambes sur les volumes mesurés. Cela ne constitue pas une promesse de 95 % dès le premier essai.
3. Mesurer les glissements sur les phases d'appui, les corrections du bassin, les vitesses articulaires et les ruptures à chaque raccord. Conserver les seuils actuels tant qu'une révision n'est pas justifiée visuellement et géométriquement.
4. Montrer des prises continues de face et de profil, pieds visibles, avec changement d'intention pendant la marche. La proximité caméra est un cas parmi d'autres ; aucune chorégraphie imposée à l'agent.
5. Pour C seulement : publier contacts, forces, chutes et récupération sous perturbations bornées ; juger sur la pose effectivement simulée et sur le maillage visible. Le succès d'un replay cinématique n'est jamais compté comme réussite physique.

L'approche caméra demande aussi une vitesse d'approche et une orientation pilotables ; la capture du téléphone et la présentation vocale restent des travaux distincts couverts par les autres recherches.
