# Feuille de route

Les critères portent sur des comportements vérifiables. Un jalon est terminé après son essai représentatif, pas après la création d'une interface vide.

## M0 — Continuité locale

**Livré dans le socle.** Monde logique, catalogue, commandes validées, persistance, pause/reprise, export Markdown et CI.

Acceptation : interrompre le scénario après la pancarte, fermer le processus, reprendre, puis constater un seul exemplaire de chaque objet et un seul événement par action. Une panne entre écriture du monde et avancement du plan doit tout annuler.

## M1 — Corps visible et contrôlable

Priorité suivante. Évaluer ARDY avec un checkpoint disponible avant de figer le moteur graphique. Construire une pièce et un humanoïde, puis la marche vers une cible et l'assise sur une chaise.

Acceptation : dix essais avec positions de chaise variées ; enregistrer contacts incorrects, glissement des pieds, pénétrations, interruptions et temps de réaction. Aucun succès déduit du seul envoi du prompt. Conserver les vidéos et conventions de conversion. Fixer le seuil de qualité après observation du premier prototype, sans annoncer de performance anticipée.

## M2 — Agent et parole synchronisés

Brancher Hermes/Astra aux actions du monde et GPT-Live à l'agent. Une activité et une mémoire communes ; propagation des interruptions aux composants concernés.

Acceptation : demander une action, la corriger pendant l'exécution et vérifier la concordance du dialogue, de l'état du monde et du mouvement. Mesurer le temps jusqu'à la réponse utile et jusqu'à la première action visible, ainsi que les échecs.

## M3 — Objets et mémoire utilisables

Ajouter la pancarte et le doudou au rendu, leurs interactions et la recherche de notes pertinentes. Faire apparaître les objets via le catalogue ; leurs positions et propriétés restent persistantes.

Acceptation : préparer une présentation, l'interrompre, redémarrer, la reprendre, retrouver un objet et appliquer une correction mémorisée. La provenance d'un souvenir doit être consultable. Le coffre ne doit pas contenir de réussites inventées.

## M4 — Initiative

Laisser l'agent choisir une activité parmi ses projets et capacités. Introduire des réveils sur événement et une cadence d'initiative configurable, avec un budget d'appels et un arrêt accessible.

Acceptation : une session d'observation montre une activité choisie, menée ou abandonnée avec une raison, sans boucle d'actions identiques ni appels continus inutiles. L'utilisateur peut suspendre l'initiative sans perdre l'état.

## M5 — Espace étendu

Lit, TV, nouveaux objets et services externes, chacun introduit avec ses usages et son périmètre. La génération d'assets et le RL pour des interactions plus complexes sont des pistes à décider à partir des limites mesurées de M1–M4.

## Décisions restant ouvertes

- Apparence, squelette, visage et identité du personnage.
- Moteur graphique retenu après l'essai ARDY.
- GPU et lieu d'exécution du contrôle moteur ; accès et budget API.
- Niveau de fidélité physique requis pour chaque interaction.
- Premier service externe utile à connecter.

