# Continuité, fluidité et réactivité du corps

Recherche du 15 septembre 2026. Lecture du code Promethee et de sources primaires ; aucune nouvelle exécution du modèle, aucun entraînement, aucune modification de production. Les solutions ci-dessous restent à qualifier sur la machine locale.

## Conclusion

**Conserver ARDY et exploiter son interface de génération continue avant de changer de modèle ou de moteur.** Le pilote Promethee transforme actuellement un modèle interactif en producteur de séquences complètes. Trois problèmes distincts se cumulent : attente avant le début, rupture de dynamique entre séquences, et répétition de la même pose entre deux observations à 20 Hz.

Un rendu interpolé réduirait les saccades visuelles mais ne rendrait pas le mouvement plus intelligent ou physiquement valide. La priorité technique est une génération à fenêtre glissante, avec historique réellement exécuté, préparation géométrique incrémentale et courte réserve de poses validées. L'interpolation vient ensuite sur une horloge commune, avec contrôle des appuis et des objets.

## Diagnostic vérifié dans le dépôt

- [ardy_worker.py](../../src/promethee/ardy_worker.py#L143) appelle `model(...)` pour toute la séquence, avec dix étapes et `crop_history_length=160`. Chaque nouvelle demande n'envoie qu'une pose initiale sous forme de contrainte. L'historique des poses du mouvement précédent n'est pas réinjecté : cette option de recadrage ne conserve pas magiquement un historique entre appels.
- [kinematic.py](../../src/promethee/kinematic.py#L199) attend génération, corrections et préparation complète du VRM avant lecture. Ensuite la pose est choisie par `int((now-play_started)*20)` à la [ligne 486](../../src/promethee/kinematic.py#L486). Un arrêt gèle la dernière pose ; ce n'est pas une décélération naturelle.
- [avatar_live.py](../../src/promethee/avatar_live.py#L141) publie uniquement le dernier instantané avec numéro de séquence. Il manque un temps de simulation transmis et un historique borné destiné à reconstruire une pose intermédiaire.
- [live.js](../../web/avatar/live.js#L178) dessine à la cadence de l'écran, mais réapplique la dernière pose ; les requêtes repartent 50 ms après la précédente réponse. Le délai réel d'observation peut donc dépasser 50 ms. Seuls les poids d'alignement des mains sont interpolés.
- [prepared-pose.js](../../web/avatar/prepared-pose.js#L56) appelle `vrm.update(0)` ; la cadence du rendu ne fait donc pas avancer les composants temporels du VRM. Ce point devra être coordonné avec le chantier des expressions pour ne pas écraser une pose préparée ni compter deux fois le temps.
- Une expérience [inertial_trial.py](../../experiments/motion/inertial_trial.py#L40) existe déjà : elle fait disparaître un décalage de pose avec une courbe cubique sur seize images. Elle n'établit pas une continuité des vitesses et ne constitue pas une qualification générale de transitions naturelles.

Les mesures [T02](../decisions/001-motion-stack.md) donnent 0,20–0,52 s par bloc de 40 poses après encodage, et 2,27–2,99 s pour texte plus génération avant corrections. La RTX 4080 16 Gio est très occupée : environ 14,58 Gio pour l'encodeur et 0,87 Gio pour ARDY dans cet essai. Les temps de 10,228 / 10,349 / 13,138 s du dernier essai complet incluent environ six secondes de lecture : **ce ne sont pas des mesures d'attente avant démarrage**. Instrumenter séparément encodage, diffusion, correction Core, préparation VRM, validation et premier affichage.

## Trois voies comparées

| Voie | Ce qu'elle apporte | Limites | Effort estimé |
|---|---|---|---|
| A. Garder les séquences et interpoler l'affichage | Gain visuel rapide, horloge explicite, meilleure présentation des poses déjà acceptées | Conserve l'attente et la perte d'historique ; peut créer du glissement entre deux poses pourtant valides | Faible à moyen, si la validation intermédiaire reste simple |
| B. ARDY continu, préparation incrémentale et interpolation contrôlée | Réutilise les poids, le squelette, la chaîne de validation et le rendu existants ; permet d'anticiper puis de réviser une intention pendant le mouvement | Demande une vraie gestion de réserve, d'annulation et d'historique ; qualité et vitesse locale à démontrer | Moyen à élevé ; voie recommandée |
| C. Contrôleur d'animation par clips qualifiés et transitions inertielles | Comportements usuels plus prévisibles, indépendants de la génération à chaque geste | Répertoire à constituer et licencier, expressivité limitée à sa couverture ; migration vers un moteur complet coûteuse | Élevé pour un remplacement ; réserve possible pour capacités bornées |

La voie C peut rester dans Three.js. Son `AnimationAction.crossFadeFrom` mélange deux clips, avec modification optionnelle de leur vitesse. Cela ne garantit pas le contact du pied ou de la main. [Code officiel Three.js](https://github.com/mrdoob/three.js/blob/dev/src/animation/AnimationAction.js)

Unreal expose des transitions inertielles, des masques par os et des corrections IK. L'inertialisation prolonge la dynamique vers une nouvelle animation ; elle n'est pas une simulation physique. La documentation conseille de la placer avant les corrections IK et prévient que les événements de l'animation sortante ne sont plus évalués après transition. Il faut donc garder les événements de prise/dépôt dans le contrôleur autoritatif. Migrer tout Promethee vers Unreal pour obtenir ce seul mécanisme ne paraît pas justifié. [Documentation Epic](https://dev.epicgames.com/documentation/en-us/unreal-engine/animation-blueprint-blend-nodes-in-unreal-engine)

## Pourquoi la voie B est crédible

La publication ARDY décrit une génération asynchrone pendant la lecture d'une réserve de poses déjà produites. Elle rapporte, sur RTX 4090, 33 ms pour quatre étapes et 63 ms pour dix étapes, avec fenêtre de 40 poses ; ces chiffres ne représentent pas la chaîne Promethee complète. Elle indique aussi que l'horizon de huit poses réagit plus vite aux changements de texte, avec des compromis de qualité. Le modèle reste cinématique et peut produire glissement et tremblement. [Publication ARDY, sections 4.1, 4.2, 5.3 et 7](https://research.nvidia.com/labs/sil/projects/ardy/assets/ardy_paper.pdf)

Le code officiel fournit précisément `autoregressive_step`, avec `init_history_sequence`, `text_feat`, translation et cap initiaux. La démo découpe un historique multiple de la taille de token, conserve une réserve, puis remplace uniquement le futur non joué. Lorsqu'elle corrige un mouvement, elle reconstruit aussi sa représentation pour les appels suivants. **Le mécanisme existe ; son intégration et ses garanties locales n'existent pas encore.** [Génération officielle](https://github.com/nv-tlabs/ardy/blob/693f74d13b3d04a0a22ce127ee79c929dd89756b/scripts/interactive_demo/generation.py), [API du modèle](https://github.com/nv-tlabs/ardy/blob/693f74d13b3d04a0a22ce127ee79c929dd89756b/ardy/model/ardy_model.py)

Le SHA HEAD vérifié par `git ls-remote` est `693f74d13b3d04a0a22ce127ee79c929dd89756b`, identique à la référence documentée localement. Il faut néanmoins tester les appels réellement installés. Conserver d'abord le checkpoint Horizon40 actuel ; Horizon8 est une variante officielle à comparer dans un essai isolé, pas un changement arbitraire du nombre de poses prédites. Les modes TensorRT et `torch.compile` sont proposés par le dépôt ; les activer seulement après mesure de la mémoire et du coût de compilation. [Dépôt et modèles officiels](https://github.com/nv-tlabs/ardy/tree/693f74d13b3d04a0a22ce127ee79c929dd89756b)

## Intégration proposée

1. **Mesurer sans modifier les comportements.** Ajouter les temps des étapes, longueur de réserve, temps du premier mouvement visible et âge de l'observation aux rapports expérimentaux. Comparer appels à froid, préchauffés, texte inédit et texte déjà encodé.

2. **Réutiliser les embeddings et le modèle chargé.** Adapter `ardy_worker.py` à un cache mémoire borné et éventuellement disque local. La démo officielle contient déjà un cache, mais le sien est indexé par texte brut. Pour Promethee, intégrer à la clé les révisions du tokenizer, de la base et des adaptateurs, le pooling et les paramètres pertinents de précision. Une absence dans le cache doit réellement encoder le nouveau texte. Aucun catalogue de routines ou préférence personnelle ne doit être injecté dans le cerveau pour rendre le cache efficace. [Cache officiel](https://github.com/nv-tlabs/ardy/blob/693f74d13b3d04a0a22ce127ee79c929dd89756b/scripts/interactive_demo/embedding_cache.py)

3. **Conserver un historique Core exécuté.** Dans `motion_process.py`/`ardy_worker.py`, transmettre un historique borné, des contraintes futures et une version d'intention. Reconstruire la représentation Core à partir des rotations locales et de la racine réellement retenues après correction. Les rotations VRM adaptées ne sont pas directement une entrée du modèle Core. Garder séparément l'état d'appui, les poids des mains et la correction du bassin VRM pour initialiser la préparation suivante. Cette interface doit être testée après prise d'objet, changement de cap, arrêt et reprise.

4. **Préparer et valider par blocs.** Faire évoluer `kinematic.py`, le processus de préparation et `prepared_avatar.py` pour alimenter une réserve de segments validés. La taille de cette réserve doit découler du P95 de la chaîne complète, pas d'un nombre choisi pour une vidéo. Si la chaîne est trop lente, conserver Horizon40 et une réserve plus grande avant d'essayer Horizon8. Le premier bloc peut démarrer dès validation sans attendre la fin de l'activité.

5. **Traiter les changements d'intention.** Une révision ne peut remplacer que des poses futures, après la frontière déjà engagée. Chaque travail porte `world_id`, session du contrôleur, ID d'exécution, version de plan et intervalle temporel. Ignorer les résultats périmés. Un arrêt explicite doit annuler la réserve et conserver la pose/les objets confirmés ; une transition naturelle de freinage doit être une trajectoire validée, jamais une extrapolation cachée. En cas de réserve vide : arrêt observé et signalé, jamais lecture d'une proposition refusée.

6. **Ajouter une horloge de présentation.** Publier temps de simulation, séquence et frontière d'annulation dans `avatar_live.py`. Un tampon client borné dans `live.js` lit avec un petit retard connu et calcule un alpha selon les timestamps. Les requêtes HTTP existantes peuvent suffire pour une première mesure ; un WebSocket ne résout ni les temps GPU ni la qualité du mouvement.

7. **Interpoler la géométrie avec ses contraintes.** Utiliser la racine et des quaternions normalisés avec SLERP, puis reconstruire le squelette par sa hiérarchie. Ne pas mélanger naïvement les coordonnées mondiales de chaque articulation : les longueurs d'os et les contacts peuvent se déformer. La fonction officielle `slerpQuaternions` suffit pour la rotation, pas pour les appuis. [Three.js Quaternion](https://threejs.org/docs/pages/Quaternion.html)

Les poses intermédiaires doivent passer les mêmes mesures géométriques : pied planté conservé, main et objet attaché calculés ensemble au même instant. Une prise/libération reste un événement discret à son instant autoritatif, sans interpolation de l'identité de l'objet tenu. Le rendu ne doit pas devancer l'attachement confirmé. Si l'on ajoute des corrections IK pendant l'interpolation, les qualifier et les journaliser comme corrections d'apparence ; ne pas les présenter comme poses du monde déjà vérifiées. Pour une première livraison, désactiver l'interpolation sur les segments dont les contacts intermédiaires ne passent pas.

`prepared-pose.js` stocke des rotations mondiales. Une interpolation en rotations locales ou une autre représentation continue impose donc un contrat explicite et une conversion testée, en tenant compte des os intermédiaires du VRM. Ne pas insérer seulement un `lerp` dans la boucle existante.

## Validation et décisions d'arrêt

Ces seuils sont des objectifs proposés, pas des résultats déjà obtenus.

- Tests déterministes CPU : timestamps irréguliers, observations perdues ou dupliquées, changement de session, arrêt pendant génération/préparation/lecture, résultats tardifs, absence de double prise/dépôt, reprise exacte au dernier checkpoint.
- Tests géométriques aux temps intermédiaires de rendu, pas seulement aux 20 poses/s sources : rotations unitaires, longueurs d'os constantes, hauteur de pied, glissement en appui, portée de main et décalage main/objet. Conserver les seuils déjà fixés ; enregistrer aussi vitesses et accélérations aux frontières, que la seule erreur de position initiale ne mesure pas.
- Essai aveugle prédéfini sur au moins trente transitions et plusieurs graines, changements de cap, vitesses, postures, contextes avec/sans objet et intentions révisées. La scène smartphone sert d'exemple de test parmi d'autres ; elle ne définit ni la personnalité ni une récompense universelle.
- Mesurer séparément première réaction, nouvelle cible atteinte, P50/P95 de génération/préparation/transport, temps total sans poses disponibles et nombre de reprises. Viser d'abord dix minutes sans épuisement de réserve sur mouvements acceptés, tout en rapportant le taux de refus.
- Cible de rendu : P95 des intervalles d'affichage inférieur à 20 ms sur écran 60 Hz ; ce critère ne certifie pas la naturalité. Revoir aussi une prise continue à vitesse réelle, sans montage, avec interruptions imprévues et caméra proche.
- Pour la réponse corporelle, définir après la mesure initiale un budget de quelques centaines de millisecondes sur intention déjà encodée. Publier séparément la latence d'un texte inédit, qui peut rester supérieure à une seconde. Ne pas cacher cette différence derrière une animation d'attente présentée comme une réponse à la consigne.

Si la préparation géométrique ne suit pas le débit ou que les nouvelles transitions augmentent les violations, ne pas assouplir les seuils pour faire passer la vidéo. Le résultat utile de l'essai sera d'identifier l'étape responsable et de comparer un contrôleur borné à clips qualifiés. Un entraînement RL complet n'est pas nécessaire pour commencer ce chantier de continuité.
