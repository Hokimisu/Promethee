# Initiative à budget explicite

L'initiative réveille le même agent Hermes que la conversation. Elle est absente
par défaut, sans objectif, besoin, routine ou préférence préchargés. Un réveil
invite l'agent à consulter l'état courant ; il peut ne rien entreprendre.

## Activation et arrêt

Le monde doit être une session au schéma 10. La migration conserve l'historique
et ajoute `initiative: null` ; elle n'active aucun appel. Configurer explicitement
un budget avant de lancer `chat` ou `voice` :

```sh
python -m promethee.cli --data-dir CHEMIN_SESSION initiative configure --budget 5
python -m promethee.cli --data-dir CHEMIN_SESSION initiative status
python -m promethee.cli --data-dir CHEMIN_SESSION initiative pause
python -m promethee.cli --data-dir CHEMIN_SESSION initiative resume
python -m promethee.cli --data-dir CHEMIN_SESSION initiative add-budget --calls 2
```

Sans `--interval`, les réveils dépendent des changements du monde. Ajouter par
exemple `--interval 60` lors de la configuration autorise aussi un réveil
périodique, au plus une décision à la fois. La cadence minimale est d'une seconde.
Le premier réveil périodique attend cet intervalle ; configurer ne lance pas
immédiatement un modèle. Les événements antérieurs à l'activation ne sont pas
réintroduits comme demandes nouvelles.

Dans `chat` et `voice`, `/pause` et `/resume` pilotent cette même pause persistante.
La commande séparée permet aussi de la changer pendant que l'hôte fonctionne.
Une pause invalide le tour autonome en cours et l'hôte ferme son processus à sa
prochaine vérification. Elle ne ferme pas un tour utilisateur plus récent et ne
demande pas l'annulation du corps. En mode vocal, elle coupe aussi la réponse
autonome en cours de préparation ou de lecture. `/cancel` conserve son sens :
couper la réponse actuelle, sans suspendre durablement l'initiative.

Fermer l'hôte termine ses appels. Le budget et la pause survivent au redémarrage ;
aucun service caché ne tourne lorsque `chat` ou `voice` est fermé. Un hôte relancé
respecte la configuration conservée, y compris une activation non suspendue.

## Réveils et budget

Les changements retenus sont les objets, les capacités actives, le statut de
confirmation du corps et les événements d'exécution terminaux. Une progression
de pose seule et les écritures de conversation ne provoquent pas de réveil.
Les états terminaux incluent les refus et interruptions : ils ne sont pas
présentés comme des actions accomplies.

Pendant une décision, l'écoute, la synthèse ou la parole, l'hôte ne démarre pas
une seconde décision. Il regroupe les événements dans un seul résumé en attente :
nombre d'événements, huit dernières références et indicateur de changement du
monde. Le journal complet reste consultable par les outils. Les événements sont
collectés par lots bornés ; un retard de collecte est résorbé avant de décider.

Le budget compte les **tours autonomes Hermes**, pas les commandes corporelles
ni chaque requête API interne à sa boucle. Il accepte de 1 à 1 000 tours ; le
rechargement est manuel et ne réactive pas une pause. Les messages de l'utilisateur
ne consomment pas ce budget. Ce n'est pas un plafond de facture : les coûts du
fournisseur et de la voix doivent être mesurés séparément.

Une réservation de budget et l'ouverture du tour sont atomiques. Une erreur de
transaction annule les deux. Après réservation, une panne du worker ou un refus
du fournisseur consomme ce tour : aucune reprise implicite ne contourne la borne.
Une correction utilisateur invalide la décision précédente selon le même contrat
que T09. Aucune quantité minimale d'activité n'est recherchée.

## Historique et mémoire

Les enregistrements de conversation indiquent `trigger: user` ou `initiative`.
Pour l'interface native Hermes, le réveil est porté dans un message explicitement
étiqueté comme événement du runtime et non comme parole humaine. Les décisions
suivantes retrouvent le même historique ; aucun second cerveau n'est lancé.

La mémoire refuse `user:TURN_ID` lorsqu'il désigne un réveil. Elle expose plutôt
`runtime:TURN_ID` avec sa provenance. Ce contexte peut sourcer une proposition,
mais ne peut attester une observation. Une observation corporelle reste fondée
sur un événement d'exécution. Les fixtures et qualifications restent exclues
de la mémoire personnelle selon le [contrat mémoire](memory.md).

## Qualification et limites

Les tests avec horloge contrôlée couvrent budget épuisé, événements regroupés
pendant un appel lent, pause/reprise, redémarrage après réservation, correction,
capacités retirées, rollback et provenance. Ils vérifient que lire la mémoire
ou écrire une conversation ne déclenche pas une nouvelle activité. Les migrations
v7 → v8 sont vérifiées avec sauvegarde et rollback.

```sh
python experiments/agent/qualify_hermes_host.py --output .local/essai-initiative-neuf --hermes-python CHEMIN_PYTHON_HERMES --hermes-root CHEMIN_HERMES --initiative
```

`.local/hermes-initiative-qualification-01` a lancé un tour budgété dans le vrai
Hermes, avec son outil MCP de lecture du monde. Le compteur est passé de 1 à 0
et aucun second tour n'a été lancé. La série vérifie aussi correction, délai,
refus fournisseur et reprise de la CLI. Son fournisseur déterministe local ne
valide ni Astra ni une capacité à former des intentions cohérentes.

T12 reste à qualifier avec le vrai modèle dans plusieurs sessions sollicitées et
non sollicitées, historiques et capacités. Les répétitions doivent être examinées
dans leur contexte ; inactivité et nouveauté ne sont pas des scores de réussite.
L'accès Astra est désormais vérifié avec l'authentification ChatGPT native de
Hermes, selon le [guide d'intégration](hermes-setup.md). Aucune initiative n'a été activée dans
une session personnelle pendant ces essais.
