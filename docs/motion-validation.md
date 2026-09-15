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

## Limites empêchant de clôturer T07

Les seuils de lecture actuels sont provisoires : erreur de cible ≤ 5 cm,
discontinuité initiale ≤ 2 cm, saut de racine ≤ 12 cm par image, racine dans la
pièce, rotations finies et orthonormales. Ils ne constituent pas une validation
des contacts ni du naturel du mouvement. Corriger et qualifier les pénétrations,
fiabiliser les postures, conserver les vidéos et vérifier des cas tenus à l'écart
de la calibration restent nécessaires.

La suite comprend aussi les essais réels de perte du processus et de reprise,
et le raccord de [l'avatar anime](assets/pixiv-vrm-sample.md). Les interactions
avec objets, Hermes, la mémoire d'agent et la voix ne sont pas encore livrés.
