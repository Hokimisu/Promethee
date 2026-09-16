# Regard, visage et gestes de parole — recherche du 15 septembre 2026

## Conclusion

Le visage actuel possède déjà les éléments nécessaires à une première présence crédible. Le blocage est surtout le raccord et la coordination, pas l'absence d'un modèle facial. Je recommande d'abord un pilote de regard et d'expressions utilisant three-vrm, puis une piste labiale horodatée sur de vrais fichiers audio français. Audio2Face mérite un essai distinct pour le flux vocal continu, après vérification de son adaptation au visage anime.

La scène proposée par l'utilisateur peut servir de test ponctuel, mais ne doit pas devenir une routine, un prompt permanent ou un objectif d'entraînement.

## État réellement observé dans le dépôt

- `web/avatar/package.json` fixe three à 0.186.0 et three-vrm à 3.5.5.
- `web/avatar/app.js` charge le VRM et rejoue des poses ; aucun pilote de parole, de clignement ou d'expression n'est présent. La boucle de lecture choisit des poses discrètes.
- `web/avatar/retarget.js:159` appelle explicitement `vrm.update(0)` pour préserver la lecture des observations, sans mouvement secondaire ajouté. Remplacer cela par une animation libre à chaque image changerait la portée du rendu et ses mesures ; il faut une couche explicite et testée.
- `web/avatar/live.js` reçoit les observations corporelles et les objets. Il n'expose pas de piste audio ni de curseur de lecture commun au visage.
- `docs/voice.md` et `docs/live-integration.md` distinguent réponse générée, démarrage de lecteur et diffusion effective. Les premiers essais du fournisseur sont simulés ; il ne faut pas déclencher la bouche à l'arrivée du texte.

Inspection directe du JSON GLB de `.local/assets/pixiv-vrm/VRM1_Constraint_Twist_Sample.vrm` :

| Fonction | Présente dans cet asset |
|---|---|
| Voyelles | `aa`, `ih`, `ou`, `ee`, `oh`, avec morph targets liés |
| Paupières | `blink`, `blinkLeft`, `blinkRight` |
| Expressions | `happy`, `angry`, `sad`, `relaxed`, `surprised`, `neutral` |
| Regard | Type `bone`, plages de mouvement définies ; les presets `look*` ne lient aucun morph |
| Morphologie | 57 morph targets nommés VRoid/Fcl ; bouche fermée présente comme morph brut, pas une base ARKit 52 |
| Conflits | `happy` mélange les overrides bouche/clignement ; `sad` et `surprised` mélangent la bouche |

L'asset est déjà documenté sous VRM Public License 1.0 dans `docs/assets/pixiv-vrm-sample.md`, avec modifications autorisées selon ses métadonnées. Ne pas confondre cette licence avec celle du logiciel.

## Trois options concrètes

### A. Regard, clignement et expressions three-vrm — socle recommandé

L'API fournit `expressionManager.setValue`, les pistes d'expression et les règles `overrideMouth/overrideBlink/overrideLookAt`. `VRMLookAt.target` suit un objet en coordonnées mondiales. Ces mécanismes existent déjà dans la dépendance installée ; aucune nouvelle IA ou formation n'est nécessaire. [ExpressionManager](https://pixiv.github.io/three-vrm/docs/classes/three-vrm.VRMExpressionManager.html), [LookAt](https://pixiv.github.io/three-vrm/docs/classes/three-vrm.VRMLookAt.html), [spécification VRM](https://vrm.dev/en/vrm1/expression/).

Implémentation proposée : un module de performance faciale reçoit une cible observée et des cues d'expression bornés ; il applique des enveloppes continues, un clignement irrégulier et des regards qui alternent entre interlocuteur et objet actif. Les yeux commencent le regard, la tête ne suit qu'au-delà d'une plage confortable. Le mouvement de tête et les gestes des bras doivent être composés par le contrôleur et devenir observables ; ne pas décaler silencieusement la tête, la main ou les objets dans le navigateur.

Un suivi caméra permanent donne un regard figé. Un sourire constant ou des hochements aléatoires sont également à éviter. Les intensités sont calibrées sur ce maillage et revues en gros plan.

Une bouche commandée uniquement par le volume peut servir au diagnostic de synchronisation, mais ne constitue pas une synchronisation phonétique. Elle n'est pas une solution suffisante pour la présentation convaincante demandée.

Effort estimé : 2–4 jours de développement et réglage pour les yeux/expressions et le contrat de cues, puis 1–2 jours de revue sur gros plans. Estimation de travail, pas engagement calendaire.

### B. Audio complet → visèmes Rhubarb → VRM — première preuve française

Rhubarb analyse un fichier WAV/OGG et fournit des positions de bouche horodatées en JSON. Son recognizer `phonetic` est prévu pour les langues autres que l'anglais. Le code est sous MIT et ses dépendances ont des licences permissives. C'est une chaîne locale CPU, utilisable sur Windows, adaptée au diagnostic vocal existant qui attend déjà la synthèse complète. [Projet et paramètres](https://github.com/DanielSWolf/rhubarb-lip-sync), [licences](https://github.com/DanielSWolf/rhubarb-lip-sync/blob/master/LICENSE.md).

Mapper ses catégories de bouche vers les cinq voyelles VRM, la fermeture et quelques morphs utiles du visage. Lisser les transitions avec un léger chevauchement des formes, sans gommer les fermetures des consonnes. Rhubarb a été conçu pour des formes 2D : cette table 3D doit être réglée et évaluée ; une sortie JSON valide ne prouve pas que le français est convaincant.

Avantages : pas de compte ni de GPU supplémentaire ; essai reproductible à partir du même audio que l'utilisateur entendra ; bon moyen de découvrir les limites du rig avant une solution lourde. Limites : analyse après obtention du fichier, cinq voyelles trop pauvres pour des consonnes précises, adaptation nécessaire des catégories ; ce n'est pas la solution finale à faible latence pour un flux vocal illimité.

Effort estimé en plus de A : 2–4 jours pour un essai contrôlé, mapping et interruption ; 2–3 jours supplémentaires si le maillage exige une fermeture/forme consonantique propre.

### C. NVIDIA Audio2Face-3D local → adaptation faciale — piste ambitieuse

Le SDK officiel est disponible en C++/CUDA sous MIT et annonce Windows/Linux, traitement batch et interactif. Il exige CUDA 12.8–12.x et TensorRT 10.13–10.x ; sa chaîne de préparation demande Python 3.8–3.10. L'isoler du Python 3.13 de Promethee. Le README recommande au moins 4 Go de VRAM. Audio2Emotion est optionnel pour notre besoin et son modèle demande une acceptation distincte ; éviter de bloquer tout le téléchargement sur cet extra. [SDK officiel](https://github.com/NVIDIA/Audio2Face-3D-SDK), [licence SDK](https://github.com/NVIDIA/Audio2Face-3D-SDK/blob/main/LICENSE.txt).

La fiche officielle du modèle Audio2Face-3D-v3.0 indique une licence NVIDIA Open Model License, des entrées rééchantillonnées à 16 kHz, une sortie de mouvement facial et la RTX 4080 parmi le matériel testé. Cela rend l'essai local plausible sur la machine confirmée par l'audit parent (RTX 4080 16 Go), sans prouver la cohabitation avec ARDY ni notre latence. [Fiche modèle](https://huggingface.co/nvidia/Audio2Face-3D-v3.0).

Ne pas brancher ces sorties directement sur les cinq voyelles VRM. Il faut un solveur/adaptateur vers le rig du personnage, ou ajouter des formes sculptées. Une réduction mal calibrée peut donner des déformations moins convaincantes que l'option B. Le visage anime peut être un bon candidat, mais la qualité de ce transfert reste à démontrer. Une API ou un exemple MetaHuman ne garantit aucune compatibilité.

Essai borné recommandé : un fichier de 30 secondes, une voix française, deux intensités d'expression ; mesurer préparation, calcul, mémoire, retard ajouté et rendu facial. Rejouer avec ARDY actif pour mesurer la concurrence GPU. Conserver l'option seulement si la revue à l'aveugle préfère son résultat et que l'interruption reste correcte.

Effort estimé : 3–5 jours pour l'essai SDK et les mesures, puis 1–3 semaines pour un transfert propre, les formes manquantes et l'intégration continue. Du travail d'artiste technique peut être nécessaire. Ne pas lancer de réentraînement avant d'avoir mesuré l'échec du modèle préentraîné et du mapping.

## Coordination proposée, commune aux options

Un seul lecteur audio doit servir de référence. Pour un rendu web, faire jouer le PCM dans le navigateur et piloter lèvres/cues depuis son curseur ; conserver la génération côté backend. Si l'audio reste dans sounddevice, exposer son compteur de frames effectivement présentées et un ancrage monotone au navigateur. Ne pas lancer deux lectures concurrentes.

Le navigateur peut relier sa sortie audio à `performance.now()` via `AudioContext.getOutputTimestamp()`. Ce lien fournit une estimation de position de sortie ; une capture audiovisuelle reste nécessaire pour mesurer la synchronisation perçue. [Documentation MDN](https://developer.mozilla.org/en-US/docs/Web/API/AudioContext/getOutputTimestamp).

Contrat minimal proposé : ID de tour, ID de génération audio, fréquence, indices d'échantillons, intervalles de visèmes, cues expressifs optionnels, état de diffusion. Les cues s'annulent avec leur génération. Les fragments arrivés après coupure sont rejetés ; les lèvres reviennent en douceur au repos. Aucun cue ne doit être traité comme preuve d'action réussie ou comme sentiment effectivement éprouvé.

L'écoute prime sur la parole en cas d'interruption. L'interruption vocale retire lèvres et gestes liés à la phrase interrompue, mais ne téléporte pas le corps et ne lâche pas un objet. Les contraintes de locomotion, d'équilibre et de manipulation gardent la priorité sur les gestes de conversation. Le regard suit l'objet utile à une prise ; la main occupée ne sert pas à souligner une phrase. Une enveloppe de retour remplace les arrêts secs.

Le cerveau choisit une intention expressive au niveau de la phrase ; il ne doit pas calculer chaque battement de paupières ou chaque pose. Le contrôleur compose les couches corporelles, puis le rendu applique les expressions compatibles et met à jour contraintes et cheveux une seule fois par image. Un `deltaTime` réel n'est activé pour les cheveux qu'après isolation de cette couche et revue de ses collisions ; les mesures de contact corporel doivent rester traçables.

## Acceptation proposée — seuils de projet à valider, pas résultats acquis

1. Corpus indépendant : au moins 12 extraits français comprenant voyelles, consonnes fermées, pauses, débit varié et trois interruptions ; ajouter dix contextes d'écoute/regard sans scénario imposé.
2. Capture réelle : p95 de décalage bouche/audio inférieur à 80 ms sur événements annotés, aucune dérive supérieure à 40 ms sur deux minutes. Mesurer sur capture audio/vidéo ; le timestamp logiciel seul ne suffit pas.
3. Coupure : aucune reprise de bouche d'une génération invalidée ; retour au repos en moins de 150 ms après la coupure audio locale, sans casser une prise ni arrêter instantanément le corps.
4. Visage : aucun clignement incomplet causé par le sourire, aucune intersection manifeste des lèvres/dents, regard sans saut ni yeux divergents ; vérifier frontalement et de profil, y compris à proximité du téléphone.
5. Cohérence : main occupée protégée, regard explicable par une cible observée, gestes expressifs modestes ; aucun geste obligatoire à chaque phrase.
6. Performance : viser 60 images/s, p95 du temps de frame inférieur à 20 ms et pas de gel supérieur à 100 ms pendant un changement d'intention, sur la machine cible avec mouvement actif.
7. Revue humaine : trois observateurs comparent baseline/A/B (puis C si disponible) sans savoir la méthode. La majorité doit préférer la version retenue pour naturel et synchro ; l'utilisateur juge ensuite une prise continue de 30–60 s, avec silence et interruption. Conserver les échecs, pas seulement le meilleur extrait.

## Ordre recommandé

Commencer A et le contrat temporel, puis B sur audio enregistré pour prouver le visage et ses formes. Ces travaux peuvent avancer pendant le déblocage du service vocal. Raccorder ensuite la diffusion réelle. Essayer C seulement si B plafonne sur la qualité ou la latence exigée. Les bras, la marche et la prise du téléphone dépendent du contrôleur corporel et ne sont pas résolus par Audio2Face.

Cette recherche n'a installé aucun paquet, téléchargé aucun modèle, entraîné aucun réseau et modifié aucun code de production. Elle vérifie les interfaces publiées et le rig local ; aucune qualité audio-faciale nouvelle n'est encore démontrée dans Promethee.
