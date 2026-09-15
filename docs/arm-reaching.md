# Portée géométrique du bras Core

Préparation de T08 : `arm_reach.reach_arm` produit une trajectoire du poignet
à partir d'une pose observée et des longueurs du squelette Core. Cette fonction
expérimentale n'est exposée ni comme action du corps ni comme outil Hermes.
Elle ne déplace aucun objet et ne valide pas une prise.

## Calcul et limites

Le bras et l'avant-bras forment une chaîne de deux segments. La cible et le
trajet doivent rester dans sa portée géométrique ; une cible impossible est
refusée, jamais projetée puis déclarée atteinte. La trajectoire utilise une
interpolation cubique du poignet sur 61 poses à 20 Hz par défaut. Le bassin,
les jambes, le torse et l'autre bras conservent leur pose. L'orientation globale
de la main reste celle du départ.

Les positions sont reconstruites depuis les rotations globales et les offsets
de repos, selon la convention Core déjà qualifiée. La pose d'entrée doit être
cohérente avec ce squelette à 1 mm près. Les noms et parents des articulations
déterminent la chaîne ; les matrices restent des rotations propres.

Cette géométrie ne connaît ni limites articulaires anatomiques, ni collisions
du bras avec le corps ou les objets, ni articulation des doigts. Un changement
de plan de flexion près d'une singularité n'est pas qualifié. Le nombre de poses
est configurable, mais aucun plafond de vitesse n'est garanti pour une durée
arbitraire. Ce composant doit rester hors du contrôleur tant que ces contraintes
et l'orientation de la main ne sont pas traitées pour l'usage considéré.

## Essai local

Le script [qualify_arm_reach.py](../experiments/motion/qualify_arm_reach.py)
prend une pose ARDY réelle, teste les deux bras, trois cibles et deux orientations
du corps, dont une avec translation. Il conserve sources, empreintes, mesures
et douze mouvements NPZ dans un nouveau dossier. Ces données sont des essais
de développement, exclus de la mémoire personnelle.

```sh
uv run --extra avatar python experiments/motion/qualify_arm_reach.py --motion SOURCE.npz --skeleton conventions.json --output .local/arm-reach-review
```

L'essai local `arm-reach-qualification-01` utilise le mouvement dont le SHA-256
est `dddb1d7e4abc299f2d9a59ed6c23e7d6c779ced85abbe6d5daf520014961b6c0`
et les conventions `ef33cf58f05abde640034e7b688670cd8074c3eb86bdf186853a68a82f69d163`.
Il mesure 29,54 cm de bras et 23,27 cm d'avant-bras, soit environ 52,81 cm entre
l'épaule et le poignet en extension. Cela ne justifie pas une portée d'un mètre.

Sur ces douze cas, l'erreur finale du poignet reste sous 0,000001 m ; les
articulations censées rester immobiles varient de moins de 0,000001 m. Le plus
grand déplacement par articulation est de 1,81 cm entre deux poses et la vitesse
maximale du poignet de 0,345 m/s. Les labels de contact des pieds sont copiés
depuis la pose initiale ; ils ne constituent pas une nouvelle mesure de contact.

L'inspection du cas `reach-02` aux poses 0, 30 et 60 dans le
[visualiseur VRM](avatar-rendering.md) montre le bras droit qui monte et le reste
du corps immobile. À l'arrivée haute, le poignet reste visiblement trop fléchi
car sa main conserve l'orientation initiale. Aucun objet n'est présent et aucune
absence de collision n'est déduite de ces trois vues. La prise reste à réaliser.

Les tests CPU couvrent conservation des segments et du reste du corps, rotation
et translation du monde, cibles impossibles, pose incohérente et géométrie non
finie. Les dépendances restent optionnelles. Le prochain raccord doit associer
géométrie de l'objet, point de contact, orientation de main et attachement suivi
par le contrôleur, avec interruptions et observations cohérentes.
