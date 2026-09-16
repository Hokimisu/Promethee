# Initiative à budget explicite

L'initiative réveille le même agent Hermes que la conversation. Elle est absente
par défaut, sans objectif, besoin, routine ou préférence préchargés. Un réveil
invite l'agent à consulter l'état courant ; il peut ne rien entreprendre.

## Activation et arrêt

Le monde doit être une session au schéma 12. La migration conserve l'historique
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

`active_turn` désigne uniquement une décision autonome encore ouverte. Sa fin,
son échec ou son remplacement efface cette référence dans la transaction qui
met à jour la conversation, sans rembourser le budget. La reprise de l'hôte
nettoie aussi les références anciennes à des tours déjà terminés. Elle ne
réémet pas leur décision et conserve leur statut historique.

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

La [scène VoxCPM2](../experiments/voice/realtime/README.md#initiative-et-reprise)
raccorde maintenant ce même ordonnanceur. Son activation navigateur est
distincte du bouton d'essai ; elle ne transforme plus les relances autonomes
en messages utilisateur. Les événements restent regroupés pendant l'écoute,
la transcription, la décision et la lecture. Une pause coupe la sortie
autonome jusque dans les trames audio tardives, sans arrêter le corps.

La décision vocale peut rester silencieuse. Seul un réveil authentifié par
l'hôte accepte `{"silent": true}` ; le JSON et l'historique natifs sont conservés,
aucun texte ni reçu audio n'est inventé. La reprise explicite `resume_world`
conserve le même monde de qualification, sa pause et son budget. Le navigateur
doit réactiver sa sortie après redémarrage avant tout nouveau départ autonome.

Ces raccords disposent de tests CPU de la composition réelle
`Initiative` / `TextHost` / `ConversationStore`, avec transports synthétiques.
Ils ne constituent pas des observations acoustiques ni une validation générale
du comportement autonome.

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

L'accès Astra est vérifié avec l'authentification ChatGPT native de Hermes,
selon le [guide d'intégration](hermes-setup.md). Aucune initiative n'a été
activée dans une session personnelle pendant ces essais.

## Observations avec Astra et ARDY réels

```sh
python experiments/agent/qualify_astra_initiative.py --output .local/essai-initiative-astra-neuf --hermes-python CHEMIN_PYTHON_HERMES --hermes-root CHEMIN_HERMES --hermes-auth-root RACINE_AUTH_HERMES --model gpt-6-astra --ardy-python PYTHON_ARDY --checkpoint-root DOSSIER_POIDS --wsl Ubuntu-22.04 --avatar CHEMIN_AVATAR_VRM
```

Le script ouvre deux mondes de qualification neufs. Le premier n'a ni historique
ni contrôleur et reçoit un seul réveil autonome. Le second utilise réellement
ARDY et l'apparence préparée ; une question utilisateur sur les capacités crée
un historique, puis deux réveils autonomes sont autorisés. Entre eux, la pause
est conservée après réouverture de l'hôte et le contrôleur est fermé. Les
capacités `move` et `posture` disparaissent effectivement, et le corps devient
non confirmé. Une cadence d'une seconde sert seulement à vérifier les bornes
de cet essai court ; ce n'est pas un réglage recommandé pour une session.

Les réponses, historiques natifs, événements et sources du code sont archivés.
Les mondes restent classés `qualification`, sans coffre mémoire ni voix. Une
seule instance ARDY doit utiliser le GPU pendant cet essai ; fermer auparavant
le pilote manuel si nécessaire, puis le relancer sur sa base existante.

La série `.local/astra-initiative-qualification-01` (graine 148123) a effectué
trois réveils et une réponse utilisateur avec `gpt-6-astra`. Astra a consulté
le monde à chaque réveil, laissé les deux mondes sans action, puis signalé le
corps non confirmé après fermeture du contrôleur. Les budgets sont passés de
1 à 0 et de 2 à 0 ; aucun appel ne s'est ajouté après épuisement. La pause du
second monde a tenu après redémarrage alors qu'il restait un appel disponible.
Les durées des réveils sont 21,19 s, 20,86 s et 20,18 s ; la réponse sollicitée
sur les capacités a pris 23,10 s.

Cette première série a révélé une référence `active_turn` conservée après une
réponse terminée. Elle n'a pas provoqué d'appel supplémentaire, mais rendait le
statut incohérent. Le correctif et ses tests couvrent fin, échec, expiration
traitée par l'hôte, correction utilisateur, reprise et rollback du résultat.

La série suivante `.local/astra-initiative-qualification-02` (graine 158123)
répète les deux contextes avec le correctif. Les trois réveils terminent en
21,02 s, 20,52 s et 22,05 s ; la question utilisateur en 25,41 s. Chaque fin
vérifie maintenant `active_turn: null`, et les deux budgets restent épuisés
sans nouveau tour. Les archives confirment zéro exécution corporelle. Le corps
non confirmé est de nouveau reconnu après fermeture du vrai ARDY. Les 363
tests passent, deux sont ignorés ; lint, format et construction réussissent.

Les choix d'inaction de ces essais ne prouvent ni absence ni présence d'une
capacité générale à former des projets. Les réponses similaires sont cohérentes
avec deux mondes vides, mais cette série courte ne mesure pas les répétitions
sur une longue durée. T12 conserve sa dépendance à la voix réelle T11 ; la
qualification textuelle ne valide pas une session autonome vocale.

## Composition réelle avec Luna, Vox et le navigateur

Le 16 septembre, l'essai local `initiative-voice-real-01` utilise Hermes 0.21.3
`2179a279`, Luna en raisonnement faible et la référence VoxCPM2 approuvée.
Le monde `session-be6e4ab39b93` est neuf, classé qualification, sans contexte
prérempli. Deux réveils sont d'abord autorisés, avec une cadence de 20 secondes.

| Étape | Observation |
|---|---|
| Premier réveil, historique vide | Décision silencieuse terminée en 15,66 s ; aucun Vox ni reçu audio |
| Deuxième réveil | Pause pendant la décision ; tour interrompu, budget consommé, aucune réponse tardive |
| Recharge explicite d'un appel | Pause conservée ; compteurs `used=2`, `remaining=1` |
| Redémarrage du même monde | Pause, compteurs, identifiant du monde et historique conservés ; aucun réveil pendant le chargement |
| Question utilisateur pendant la pause | Réponse terminée en 7,19 s ; budget inchangé ; lecture navigateur complète de 8,64 s, zéro sous-alimentation |
| Reprise explicite | Dernier réveil silencieux terminé en 6,78 s ; `used=3`, `remaining=0`, aucun tour supplémentaire après plusieurs cadences |

Le premier redémarrage, demandé avant expiration du bail de cinq secondes,
est refusé. Après expiration et vérification de l'absence des anciens workers,
la reprise fonctionne avec la réconciliation existante. Une seule instance
Vox et une seule instance ARDY sont présentes. Les nouveaux artefacts corporels
sont séparés des précédents, et le dernier historique natif contient encore
le silence initial ainsi que la question utilisateur.

La réponse utilisateur commence à être lue 7,76 s après ouverture de son tour.
Cette mesure n'est pas une garantie de conversation fluide. Les deux décisions
autonomes terminées restent silencieuses ; l'essai vérifie leur droit au silence,
pas leur expressivité vocale ni une capacité générale à former des projets.
La scène corporelle présente encore des poses de fin de geste peu naturelles,
observées visuellement. La pause vocale ne les remplace pas artificiellement.

Une demande utilisateur supplémentaire de retour debout a produit deux rejets
de commande, puis une correction native acceptée et terminée. La réponse a pris
22,52 s et a été lue complètement. L'image finale conserve pourtant une pose
peu reposante ; le résultat `completed` ne suffit donc pas à qualifier cette
allure. La corrélation a ensuite isolé un [défaut du lecteur après reprise](live-avatar.md#ordre-des-os-après-reprise) :
l'ordre des os changeait sans reconstruire les correspondances. Sur le même
VRM et les mêmes données, le correctif ramène l'erreur maximale de 48,54 cm
à l'arrondi numérique. L'émetteur stabilise aussi son ordre. L'arrêt de présence
conserve toujours exactement la dernière pose sans phase de retour ; cette
question de naturel reste distincte du défaut de lecture corrigé.

Pour reproduire le protocole : activer deux tours dans un monde neuf, observer
une fin, mettre en pause pendant le tour suivant, ajouter explicitement un
appel par la CLI, arrêter le serveur puis reprendre via `resume_world`. Vérifier
la pause et les compteurs avant d'envoyer une question, puis reprendre le dernier
tour. Le contenu des décisions n'est pas prescrit ; un choix différent du
silence n'invalide pas le test. Les archives locales conservent les états,
empreintes de sources, identifiants, statuts et reçus de lecture.

T11 reste ouvert pour le microphone matériel, l'interruption acoustique et
la latence. Ce raccord ne remplace pas les observations textuelles antérieures
avec retrait effectif des capacités, ni une qualification longue de l'initiative.
