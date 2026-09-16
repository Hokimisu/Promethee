# Boîte à Ariane — première qualification locale

Essais des 16–17 septembre 2026 dans un monde interactif jetable et son coffre
séparé. Aucun événement de ces essais n'est repris dans le monde personnel.
Mode d'emploi et limites : [ouvrir la boîte](../pet-environment.md).

## Périmètre livré

Les tranches B01–B04 relient le même Hermes résident, l'initiative, les outils
mémoire, VoxCPM2 et le contrôleur ARDY à un monde personnel. La scène n'exige
plus de scénario de 60 secondes. Les interventions souris sont enregistrées
avec un auteur extérieur ; les contacts proviennent de la simulation.

La vie s'active explicitement, avec un budget visible. Le dernier spectateur
absent suspend le corps et les décisions. Aucun emploi du temps, usage d'objet,
gag ou obligation de répondre n'est ajouté au prompt.

## Observations dans le navigateur

| Essai | Résultat observé |
| --- | --- |
| Apparition et déplacement d'objets | Balle et doudou visibles, identifiants et positions conservés après plusieurs redémarrages |
| Glisser-déposer d'Ariane | Déplacement confirmé du corps vers environ `[0,87 ; -0,89]` m, pose conservée, événement attribué à l'utilisateur |
| Lancer vers le bord de la pièce | Contacts sol puis mur, immobilisation vers `[-3,30 ; 0,06 ; 3,76]` m ; Hermes a commenté le trajet observé |
| Lancer vers Ariane | Contact de la capsule corporelle vers `[0,82 ; 0,44 ; -0,57]` m, puis rebond au sol ; aucune impulsion corporelle revendiquée |
| Parole après lancer | 5,44 s d'audio, génération en 3,99 s, premier PCM en 0,122 s, lecture terminée et zéro sous-alimentation mesurée |
| Réveils sans parole | Plusieurs décisions ont produit une sortie silencieuse |
| Recharge en pause | Budget de 0 à 10 appels restants, 8 appels déjà utilisés conservés ; pause toujours active |
| Prise puis déplacement avec objet tenu | Après correction, prise réelle `completed`, doudou visible dans la main ; déplacement externe d'environ `[-1,59 ; +0,53]` m appliqué au corps et à l'objet ensemble |
| Dépôt à portée de la main | Résultat `completed`, attachement retiré ; lors du déplacement suivant d'Ariane, le doudou reste à sa position |
| Présence corporelle | Horizons joués, mais refus intermittents d'appui prédit ; la naturalité continue reste non qualifiée |

Ce sont des essais courts, pas une validation de vie autonome sur plusieurs
jours. La lecture numérique ne remplace pas une évaluation acoustique humaine.
La scène fournit des collisions simplifiées pour les balles, pas une simulation
dynamique complète du personnage ou du doudou.

## Prise et transport

Le solveur existant ne baisse pas le tronc. Avec la pose debout mesurée, le
minimum théorique de hauteur des poignets est d'environ 0,91–0,94 m ; un objet
au sol reste hors d'atteinte. Le sélecteur **En hauteur · 1,25 m** présente un
doudou à hauteur manipulable, sans simuler une table inexistante.

Un essai de prise à portée des bras a aussi révélé une discontinuité de
préparation : la présence utilisait `--plant`, tandis que la prise recalculait
les pieds avec `--settle`. Le premier pied différait de 4,42 cm de la pose déjà
affichée. Le contrôleur a refusé l'action et conservé un résultat `failed`.
La parole d'anticipation du modèle n'a pas transformé ce refus en réussite.

La correction conserve les appuis VRM déjà préparés pour les seules interactions
dont le bassin et les jambes Core restent stationnaires. Les deux validateurs
vérifient l'origine exacte et refusent une modification des jambes ou des appuis.
Le replay des 91 poses précédemment refusées passe : 0 m de différence initiale,
0 m/s de glissement des semelles, contacts des deux pieds sur 91/91 poses et
erreur de main maximale de 2,13 × 10⁻⁸ m. Aucun seuil n'est élargi.
La prise a ensuite été rejouée dans le navigateur avec Hermes et le contrôleur
réels : résultat `completed`, attachement observé et doudou visible dans la main.
Un premier dépôt choisi hors de portée a été refusé. Le dépôt à la position
effectivement atteinte par la main a ensuite réussi, sans attachement restant.

Le transport pendant une présence générique a été exclu : sur 40 poses debout
archivées, 9 produisaient un contact de l'objet avec une cuisse. Un objet tenu
suspend donc les gestes génériques et doit être posé avant locomotion ou
changement de posture. Le déplacement direct par l'utilisateur conserve
l'attachement à la main ; ce n'est pas une marche avec objet.

Pour la présence au repos, les deux refus de qualité déjà connus peuvent être
retentés après une seconde, au maximum trois échecs consécutifs. Une lecture
réellement acceptée réarme ce compteur ; une erreur de stockage ne le fait pas.
Si une sauvegarde échoue après arrêt local lors d'une intervention ou d'une
pause, le contrôleur abandonne son bail afin de ne pas conserver une action
durable dont le pilote a disparu.

Le glisser du personnage utilise un plan à la hauteur du point touché pour
calculer sa translation horizontale. Une projection sur le sol amplifiait le
déplacement du curseur près de l'horizon. Les volumes de sélection des maillages
articulés sont recalculés à la saisie, après déplacement des os. Après correction,
un glisser horizontal de 145 pixels suit le torse dans le navigateur et laisse
le doudou précédemment posé sur place. Les cheveux gardent une inertie visuelle
transitoire lors de ces translations directes.

## Vérifications reproductibles

Les tests automatisés couvrent les événements et observations atomiques,
retransmissions, réponses tardives, saisies concurrentes, perte du spectateur,
reprise, pause et recharge, attachements, collisions balayées et vitesses
bornées. Les fixtures CPU ne qualifient pas ARDY ou l'apparence VRM.

```sh
python -m pytest -q
python -m pytest -q experiments/voice/realtime
cd experiments/voice/realtime/web
npm test
npm run build
```

Conserver des répertoires temporaires distincts pour des exécutions parallèles
de pytest. Les modèles, références vocales, journaux et captures restent locaux.
Les essais prolongés, le ramassage au sol et le transport animé restent ouverts.
