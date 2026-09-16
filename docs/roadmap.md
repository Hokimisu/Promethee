# Feuille de route

Les jalons ouvrent des capacités techniques. Leurs critères vérifient la cohérence, la fiabilité et le contrôle utilisateur, sans imposer une activité ou une personnalité à l'avatar. Les situations d'essai doivent varier ; une démonstration réussie ne suffit pas à valider un jalon.

## Priorité produit — 16 septembre 2026

Construire la [boîte à Ariane](pet-mode.md) à partir du socle existant :
continuité et initiative avec Hermes, objets réellement présents, interventions
directes de l'utilisateur, puis lancers. La faible latence vocale, GPT-Live et
la génération motrice immédiate ne bloquent plus cette première expérience.
VoxCPM2 reste la voix retenue ; les animations continuent entre les décisions.

Une première [version jouable](pet-environment.md) raccorde ces quatre tranches.
Les [essais locaux](research/19-pet-environment.md) ne ferment pas la qualification
de vie autonome prolongée ou les limites motrices.

Les jalons ci-dessous restent des contrats techniques, avec leurs limites
documentées. La nouvelle priorité ne les déclare pas terminés et ne demande
pas de recommencer les tickets déjà livrés. La qualification acoustique de M2
peut avancer séparément du mode à observer, utilisable avec texte et voix sortante.

Le [plan d'implémentation](implementation-plan.md) décline ces jalons en tickets ordonnés, avec les fichiers concernés et les vérifications attendues. Pour commencer à coder, suivre T00 puis T01 ; les jalons ci-dessous conservent la vue produit.

## M0 — Continuité locale

**Livré dans le socle.** Monde logique, catalogue, commandes validées, persistance, pause/reprise, export Markdown et CI.

Acceptation : des tests déterministes vérifient la persistance, la reprise après redémarrage, l'absence de double exécution et le rejet des actions invalides. Une panne entre écriture du monde et avancement du plan doit tout annuler. La fixture CLI fournit un cas reproductible ; son contenu n'est pas une cible produit.

## M1 — Corps visible et contrôlable

Priorité suivante. Évaluer ARDY avec un checkpoint disponible avant de figer le moteur graphique. Construire un espace et un humanoïde, puis valider les déplacements, les changements de posture et les contacts élémentaires. Les objets d'essai sont interchangeables selon la capacité évaluée.

Acceptation : varier les positions initiales, les cibles, les supports et les moments d'interruption ; enregistrer contacts incorrects, glissement des pieds, pénétrations et temps de réaction. Aucun succès déduit du seul envoi du prompt. Conserver les vidéos et conventions de conversion. Définir les seuils techniques après les premiers essais de calibration, puis vérifier sur des situations distinctes.

## M2 — Agent et parole synchronisés

Brancher Hermes/Astra aux actions du monde et GPT-Live à l'agent. Un contexte et une mémoire communs, avec ou sans activité active ; propagation des interruptions aux composants concernés.

Acceptation : tester la conversation seule, une demande d'action, sa correction et son interruption ; vérifier la concordance du dialogue, de l'état du monde et du mouvement. Mesurer le temps jusqu'à la réponse utile et, lorsqu'une action est demandée, jusqu'à son début visible, ainsi que les échecs. Parler ne doit pas déclencher automatiquement une activité physique.

## M3 — Objets et mémoire utilisables

Ajouter au rendu des objets couvrant plusieurs capacités d'interaction et la recherche de notes pertinentes. Leur choix sert la couverture technique ; aucun objet n'est rendu obligatoire dans l'usage. Les positions et propriétés restent persistantes.

Acceptation : varier objets, historiques et demandes pour vérifier la récupération d'informations pertinentes, les corrections et la continuité après redémarrage. Inclure un historique vide et un objet déplacé ou absent. La mémoire permet de retrouver l'état d'une activité sans en imposer la reprise. La provenance d'un souvenir doit être consultable ; les données de test restent hors de la mémoire de l'agent.

## M4 — Initiative

Permettre à l'agent de former et réviser des intentions, d'explorer ou de rester sans activité. Introduire des réveils sur événement et une cadence d'initiative configurable, avec un budget d'appels et un arrêt accessible. Aucun projet ni usage d'objet n'est préchargé pour provoquer un comportement attendu.

Acceptation : observer plusieurs sessions avec et sans sollicitation, avec des dispositions et historiques différents. Vérifier le respect des contraintes, la cohérence des effets et la possibilité de suspendre l'initiative sans perdre l'état. Ne pas noter la quantité d'activités, la réutilisation des objets de démonstration ou la conformité à un récit. Examiner aussi les boucles répétitives et les choix qui persistent malgré un changement de contexte. L'inaction seule n'est ni un échec ni une réussite.

## M5 — Espace étendu

Étendre les objets, les capacités et les services externes à partir des besoins observés et des choix de l'utilisateur. Les exemples de lit ou de TV ne sont pas un programme imposé. La génération d'assets et le RL pour des interactions plus complexes sont des pistes à décider à partir des limites mesurées de M1–M4.

## Décisions restant ouvertes

- Apparence, squelette, visage et identité du personnage.
- Moteur graphique retenu après l'essai ARDY.
- GPU et lieu d'exécution du contrôle moteur ; accès et budget API.
- Niveau de fidélité physique requis pour chaque interaction.
- Premier service externe utile à connecter.
