# Comparaison du guidage ARDY

Cette calibration ne change pas le pilote livré. Les nouveaux réglages corrigent
certains défauts tout en en introduisant d'autres ; aucun n'est qualifié comme
amélioration générale de la marche.

Le checkpoint épinglé `ARDY-Core-RP-20FPS-Horizon40` déclare
`num_base_steps: 10` dans son `config.yaml`. Le pilote utilise déjà ces dix
étapes. L'interface de démonstration officielle expose un réglage, mais cela
n'autorise pas vingt étapes sur ce checkpoint. Le premier essai à vingt étapes
a provoqué une erreur d'index CUDA avant toute sortie de mouvement. Son journal
reste dans `.local/denoising-calibration-20` ; les erreurs suivantes du même
processus ne constituent pas des essais indépendants, le contexte CUDA étant
déjà invalide. L'essai à cinquante étapes n'a pas été lancé.

Le [script de comparaison](../experiments/motion/denoising_trial.py) vérifie
maintenant la borne du checkpoint avant de lancer le worker. Une demande de
vingt étapes est effectivement refusée à cette étape, sans créer de dossier
d'essai ni charger le GPU. Il arrête aussi la série après une erreur CUDA.

La comparaison suivante conserve dix étapes et varie uniquement les deux
poids de guidage ensemble : `(1,1)`, `(2,2)` livré, `(3,3)`. Les graines, textes,
contraintes, poses initiales et corrections géométriques restent identiques.
Quatre requêtes des séries 15–16, désormais utilisées comme calibration,
constituent le lot. Il s'agit de générations hors monde, pas de nouvelles
exécutions `completed` du runtime.

| Requête archivée | Guidage 1 | Guidage 2 livré | Guidage 3 |
|---|---|---|---|
| 15, retour debout | Saut articulaire max 0,150 m | Refusé dans le runtime : 0,336 m | Saut articulaire max 0,120 m |
| 16, premier trajet | Refusé : correction de hauteur totale excessive | Refusé : image 39 sans appui prédit | Contacts mesurés conformes ; bassin incliné jusqu'à 55,24° |
| 15, premier trajet | Contacts conformes ; inclinaison max 40,56° | Terminé ; inclinaison max 28,63° | Refusé : correction du sol supérieure à 5 cm |
| 16, retour | Contacts conformes ; inclinaison max 11,97° | Terminé ; inclinaison max 9,64° | Contacts conformes ; inclinaison max 11,12° |

Le saut du retour debout existe dans la sortie brute : 0,33566 m entre les
images 18 et 19, articulation 11, contre 0,33554 m après correction. Il ne
provient donc pas du correcteur de jambes. Les deux guidages alternatifs
réduisent ce saut sur cette requête ; cela ne prouve pas leur fiabilité sur de
nouvelles postures. Aucun réglage conditionnel ni nouvelle tentative cachée
n'est ajouté au runtime.

Pour le trajet de la série 16 avec guidage 3, le contact de surface est présent
sur 120 images sur 120, avec glissement maximal/P95 de 0,08928/0,02876 m/s et
erreur à la cible de 32,49 mm. Ces mesures passent les seuils existants malgré
l'inclinaison. La vidéo locale `video-guidance-calibration-3/motion.mp4` conserve
le vrai maillage Core sans correction de rendu. Une géométrie de contact
conforme ne suffit pas à qualifier la naturalité ou l'équilibre.

Les sources, configuration du modèle, critères, empreintes des requêtes,
réponses, sorties brutes et corrigées restent dans
`.local/guidance-calibration-1` et `.local/guidance-calibration-3`. Ces données
de qualification ne rejoignent aucune mémoire personnelle.

Reproduction sous Linux/WSL dans l'environnement ARDY, avec `src` dans
`PYTHONPATH` :

```sh
python experiments/motion/denoising_trial.py --request JOB-request.json --output NOUVEAU_DOSSIER --steps 10 --guidance 3 --ardy-python /chemin/ardy-env/bin/python --checkpoint-root /chemin/checkpoints
```

Répéter `--request` pour plusieurs requêtes archivées. Le script lance une copie
du worker, n'ouvre aucun monde SQLite et n'assimile pas une réponse `generated`
à une exécution réussie. Le guidage du pilote reste `(2,2)` ; T07 reste ouvert.
