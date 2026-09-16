# Essai de continuation ARDY avec historique corrigé

Essai du 15 septembre 2026, après la [recherche sur la continuité](02-continuity.md).
Le code de production reste celui de `992bb4d87083bbff141c668bd073b5ce5e7d8bd7`.
Les deux nouveaux scripts sont des expériences hors session : ils ne commandent
pas un corps en direct et n'écrivent aucun souvenir ni résultat d'action.

**Résultat : la réinjection d'un historique corrigé fonctionne sur les poids
actuels. Elle ne suffit pas à obtenir une marche naturelle et fiable.** Sur trois
demandes, deux passent les contrôles Core, une seule passe aussi la préparation
VRM complète. Cette dernière présente une inclinaison finale peu convaincante.
Ces trois cas ne constituent pas un taux de fiabilité général.

## Méthode

- ARDY Core Horizon40, 20 Hz, dix étapes de génération, guidage `(2, 2)` ; source
  ARDY `693f74d13b3d04a0a22ce127ee79c929dd89756b` et poids de la
  [qualification existante](../decisions/001-motion-stack.md).
- Même archive initiale pour les trois cas : les 40 dernières poses de
  `.local/runtime-transition-holdout-01/motions/216334cb992d49b0853969dd1ba514a0-processed.npz`,
  SHA-256 `965cd6632c35e3ca1e17637c0d49c199c5c5dfdd479506fa058f49d089fd3a96`.
  Racine initiale XZ : environ `(-0,0103 ; 0,0100)` m.
- Consigne : `A person walks to the target and stops.` Trois blocs de 40 poses,
  soit six secondes proposées. Aucun changement de consigne en cours d'essai.
- Reconstruction des caractéristiques ARDY depuis les rotations et positions
  Core corrigées. L'historique réencodé doit conserver les articulations à moins
  de 2 mm. Seules les nouvelles poses sont retenues ; l'approximation de
  l'ancien historique par l'autoencodeur est écartée.
- Corrections et seuils Core existants, puis préparation VRM de chaque bloc
  depuis la dernière apparence préparée. Le téléphone et les gestes vocaux ne
  sont pas inclus dans cet essai.
- Une graine par cas, sans recherche de meilleure prise. Les cas 02 et 03 ont
  été fixés ensemble après l'inspection du cas 01, avant leur exécution. Ils
  complètent le diagnostic ; ce n'est pas une batterie finale indépendante.

## Résultats conservés, y compris les refus

| Cas | Graine | Cible XZ (m) | Core | VRM et inspection |
|---|---:|---|---|---|
| 01 | 128123 | `(0,28 ; -0,07)` | 3 blocs acceptés ; erreur finale 16,1 mm | 120 poses préparées. Poses 0, 39, 60, 90 et 119 inspectées dans le lecteur : début presque immobile et inclinaison finale prononcée. Naturalité non validée |
| 02 | 128124 | `(0 ; 1)` | 3 blocs acceptés ; erreur finale 0,72 mm | Deuxième bloc refusé : correction du bassin VRM supérieure à 5 cm. Aucun export complet |
| 03 | 128125 | `(0,8 ; -0,4)` | Troisième bloc refusé : phase prédite sans appui | Préparation VRM complète non lancée |

La reconstruction de l'historique atteint au maximum 0,026 mm d'écart sur ces
essais. Les raccords Core acceptés restent sous 0,044 mm d'écart de position
après correction. Ce contrôle n'établit pas la continuité des vitesses ou des
accélérations. Les poses inspectées ne remplacent pas l'évaluation d'une prise
continue ni la validation des contacts intermédiaires à l'affichage.

Le cas 01 déplace sa racine Core de 31,4 cm, son pied droit de 31,8 cm et son pied
gauche de 4,85 mm entre les extrémités. Il serait donc incorrect de conclure,
depuis la seule posture VRM finale, que le générateur n'a déplacé aucun pied.
La comparaison des différentes étapes doit localiser la dégradation visible.

## Temps mesurés

Pour le cas 01, chargement du modèle : 5,39 s ; encodage du texte : 6,83 s.
Ces opérations précèdent la génération et ne sont pas incluses ci-dessous.

| Bloc de deux secondes | Historique, génération et corrections Core | Préparation VRM | Somme indicative |
|---|---:|---:|---:|
| 1 | 1,628 s | 1,135 s | 2,763 s |
| 2 | 0,485 s | 1,086 s | 1,572 s |
| 3 | 0,468 s | 1,010 s | 1,478 s |

La génération GPU seule prend respectivement 0,686, 0,207 et 0,181 s. Le coût
complet d'un bloc est donc sensiblement supérieur. Les phases Core et VRM ont
été exécutées séparément ; leur somme n'est pas un benchmark de session en
direct. Aucun affichage concurrent, changement d'intention, épuisement de
réserve ou maintien pendant dix minutes n'a été testé. Le service d'encodage
était déjà démarré ; son démarrage n'est pas compté.

Ces mesures justifient un essai de génération pendant la lecture. Elles ne
garantissent ni un démarrage immédiat ni une réserve toujours suffisante.

## Reproduire

Le [script Core](../../experiments/motion/continuous_trial.py) utilise
l'environnement ARDY isolé et le service d'encodage décrits dans le
[guide d'expérience](../../experiments/motion/README.md). Les archives citées
restent locales et ne sont pas livrées dans Git. Un autre historique valide peut
être fourni, mais ce sera un nouvel essai.

Exemple sous WSL, depuis le dépôt monté :

```sh
/root/.local/share/promethee/ardy-env/bin/python experiments/motion/continuous_trial.py \
  --source .local/runtime-transition-holdout-01/motions/216334cb992d49b0853969dd1ba514a0-processed.npz \
  --checkpoint-root /root/.local/share/promethee/checkpoints \
  --output .local/continuous-history-new \
  --seed 128123 --text 'A person walks to the target and stops.' --target 0.28 -0.07
```

Le [script d'apparence](../../experiments/motion/qualify_continuous_appearance.py)
utilise le Python du projet, Node et les dépendances du rendu déjà installées.
Il exige une observation initiale avec une apparence préparée correspondant
exactement à la dernière pose source. Exemple PowerShell :

```powershell
.venv/Scripts/python.exe experiments/motion/qualify_continuous_appearance.py `
  --trial .local/continuous-history-new `
  --observations .local/runtime-transition-holdout-01/observations.json `
  --skeleton .local/runtime-transition-holdout-01/motions/conventions.json `
  --avatar .local/assets/pixiv-vrm/VRM1_Constraint_Twist_Sample.vrm `
  --output .local/continuous-history-appearance-new
```

Chaque sortie exige un dossier neuf. Les archives brutes, poses corrigées,
mesures et refus restent dans `.local/continuous-history-trial-01` à `03` et
`.local/continuous-history-appearance-01` à `02`. Les fichiers `report.json`
distinguent explicitement passage géométrique et intégration au runtime.
L'inspection visuelle est consignée ici séparément de ces rapports automatiques.

## Prochaine étape motivée par les mesures

Comparer les cas conservés aux quatre étapes : sortie brute, correction Core,
adaptation VRM seule et appuis VRM. Le cas 02 donne un exemple précis où une
trajectoire acceptée par Core est refusée par l'apparence ; le cas 01 rappelle
qu'un succès géométrique peut rester visuellement mauvais. Garder les seuils
et les refus visibles pendant cette comparaison.

Le contrôleur continu devra ensuite conserver l'historique **effectivement
exécuté**, préparer le futur pendant la lecture et rejeter les résultats d'une
ancienne intention. Les historiques de cette expérience sont des propositions
enchaînées hors session ; ils ne valident pas cette gestion concurrente.

Aucun entraînement RL, nouvelle voix ou nouveau comportement autonome n'est
livré par cet essai. T11 et la qualification d'une présence naturelle restent
ouverts.
