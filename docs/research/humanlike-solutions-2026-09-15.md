# Ariane : solutions pour une présence naturelle

Recherche du 15 septembre 2026, sur Promethee `992bb4d87083bbff141c668bd073b5ce5e7d8bd7`. Quatre agents ont étudié les cinq blocages dans des analyses dédiées, suivies d'une synthèse et d'une vérification croisée. Sources : code local, archives d'essais et documentation officielle. Aucun nouveau modèle n'a été installé ou entraîné ; les solutions proposées ne sont pas encore qualifiées dans Promethee.

**Recommandation : conserver Astra/Hermes, ARDY et le rendu VRM pour le prochain essai. Le travail prioritaire est de transformer les mouvements par séquences en un contrôle continu, puis de synchroniser corps, regard et audio.** Une migration complète de moteur ou un entraînement RL ne sont pas les premières étapes justifiées par les observations.

L'expérience souhaitée — se présenter, s'approcher, manipuler la caméra comme un téléphone — sert à évaluer une capacité. Elle ne doit devenir ni une routine obligatoire, ni une personnalité préchargée, ni une récompense d'entraînement.

**Complément expérimental :** un [essai réel de continuation](06-continuous-trial.md)
réinjecte maintenant l'historique corrigé, hors session. Sur trois demandes, deux
passent Core et une seule passe aussi la préparation VRM ; cette dernière ne
donne pas encore une marche convaincante. Cela confirme la faisabilité de
l'historique et la nécessité de travailler les appuis et l'adaptation au VRM.
Le contrôleur de production reste inchangé.

Une étape ultérieure a identifié puis corrigé un [ancrage excessif du pied](../avatar-foot-roll.md)
lorsque seule la pointe devait rester au sol. Le cas 02 passe désormais la
préparation VRM, avec les mêmes poses. Les nouvelles séries confirment toutefois
que d'autres déplacements restent refusés. Les mesures ci-dessus décrivent
l'état initial de la recherche ; le guide lié présente ce correctif et ses limites.

Le [mode continu expérimental](../continuous-motion.md) intègre ensuite cette
continuation au runtime : blocs validés, futur distinct de l'historique exécuté,
réutilisation du texte pendant une action et annulation. Les premiers essais
réels confirment ce raccord, mais conservent attentes et refus de marche.
Les propositions ci-dessous restent la feuille de recherche initiale.

## Décisions proposées

| Blocage | Solution à essayer en premier | Alternative si elle échoue | Nature du travail |
|---|---|---|---|
| Marche et appuis | Comparer les étapes ARDY → corps Core → VRM, puis corriger les défauts localisés et contrôler les intersections entre jambes | Bibliothèque de locomotion validée ; suivi physique préentraîné si la physique devient nécessaire | Incertitude de qualité, à mesurer |
| Continuité | Mode autorégressif ARDY avec historique exécuté, génération pendant la lecture et réserve de poses validées | Contrôleur par animations pour les capacités qui restent fragiles | Évolution importante du contrôleur |
| Visage et parole | Regard et expressions VRM natifs ; lèvres pilotées par l'horloge de l'audio réellement joué | Audio2Face après essai de transfert vers le visage anime | Intégration et réglage du personnage |
| Caméra POV | Téléphone comme objet du monde, point optique, prise orientée et caméra liée à sa transformation | Simulation physique de la prise si les interactions l'exigent | Extension des capacités d'objet et de main |
| Voix réelle | Qualifier GPT-Live avec délégation vers le même Hermes ; corriger l'interruption et les sorties tardives | Chaîne transcription → Hermes → synthèse pour diagnostic | Accès au service et travail logiciel |

Ces choix constituent une proposition de développement, pas une annonce de fonctionnalités livrées.

## 1. Fiabiliser la marche sans masquer les échecs

Le dernier essai indépendant termine deux postures et un déplacement, tandis qu'un autre déplacement est refusé. Les contrôles actuels mesurent la géométrie des appuis ; ils ne simulent pas les forces ni l'équilibre. Cette petite série ne permet pas d'annoncer un taux de fiabilité général. [Preuves locales](../completion-audit.md)

Le premier essai doit isoler quatre états d'une même demande : sortie ARDY brute, correction des appuis Core, adaptation au VRM, puis correction des appuis VRM. Les mêmes graines et cibles permettent de repérer où apparaissent glissement, jambes croisées ou correction excessive du bassin. L'hypothèse d'un conflit entre les deux adaptations est plausible, mais elle reste à démontrer.

Ajouter ensuite un contrôle d'intersection des cuisses et mollets, et des contraintes explicites de trajectoire, vitesse et orientation. Augmenter les tolérances pour faire passer la démonstration ne résoudrait pas le défaut visible.

Si cet essai ne donne pas une marche acceptable, une bibliothèque de départs, marches, virages et arrêts fournit une base plus prévisible. Astra garde le choix de la destination ; les animations constituent des capacités motrices, pas un récit imposé. Il faut des données dont les droits correspondent à l'usage retenu. La référence [Motion Matching de Daniel Holden](https://github.com/orangeduck/Motion-Matching) distingue notamment licence du code et licence de ses mouvements.

Pour une vraie physique, [ProtoMotions SOMA BONES-SEED](https://github.com/NVlabs/ProtoMotions/blob/main/data/pretrained_models/motion_tracker/soma-bones/MODEL_CARD.md) fournit un suivi préentraîné sous IsaacLab. Il impose son corps et ses conventions : les références Core puis le rendu VRM devraient être adaptés. Les poids publics [SONIC](https://huggingface.co/nvidia/GEAR-SONIC) ciblent le robot G1 ; ce n'est pas un remplacement direct de notre humanoïde.

**Décision : diagnostic court de l'existant, puis choix fondé sur une batterie réservée et les vidéos. La physique reste un essai distinct.** [Analyse détaillée](01-locomotion.md)

## 2. Exploiter la génération continue déjà disponible

Le pilote actuel demande toute une séquence et attend sa préparation avant lecture. Il transmet une pose initiale, sans réinjecter l'historique du mouvement précédent. L'affichage redessine la dernière observation reçue ; une cadence d'écran élevée ne crée donc pas des poses intermédiaires.

L'interface officielle ARDY possède déjà un pas autorégressif avec historique et contraintes futures. La référence inspectée correspond au commit déjà documenté dans le projet. C'est une possibilité d'intégration vérifiée dans le code officiel, pas une performance nouvellement obtenue chez nous. [API ARDY](https://github.com/nv-tlabs/ardy/blob/693f74d13b3d04a0a22ce127ee79c929dd89756b/ardy/model/ardy_model.py), [démonstration continue](https://github.com/nv-tlabs/ardy/blob/693f74d13b3d04a0a22ce127ee79c929dd89756b/scripts/interactive_demo/generation.py)

L'évolution proposée comporte quatre éléments :

1. Conserver un historique borné du corps Core effectivement exécuté, avec l'état d'adaptation VRM séparé.
2. Générer et valider le futur pendant la lecture des poses déjà acceptées ; invalider les anciens résultats lors d'un changement d'intention.
3. Réutiliser les encodages de texte dans un cache borné et lié aux versions du modèle. Un texte inédit doit toujours être encodé.
4. Horodater les observations et interpoler les rotations pour l'affichage, en vérifiant aussi les appuis et les attachements entre les poses sources.

Les temps de 10–13 secondes du dernier essai incluent environ six secondes de mouvement. Ils ne doivent pas être présentés comme le temps d'attente avant son début. Il faut mesurer séparément encodage, génération, corrections, préparation et premier affichage.

Un arrêt progressif doit lui-même être une trajectoire contrôlée. Si aucune suite valide n'est prête, le système doit signaler l'arrêt ; il ne peut pas inventer une marche pour cacher le manque de données.

**Décision : essayer ce fonctionnement avec les poids actuels avant de remplacer ARDY.** [Analyse détaillée](02-continuity.md)

## 3. Donner un visage à la parole

L'inspection du VRM local retrouve cinq voyelles, des clignements, plusieurs expressions, un regard commandé par les os et les articulations des doigts. Le personnage dispose donc déjà d'une base exploitable. Ses formes faciales sont celles de VRoid ; elles ne constituent pas un visage ARKit directement compatible avec n'importe quel modèle facial.

Commencer par les [expressions](https://pixiv.github.io/three-vrm/docs/classes/three-vrm.VRMExpressionManager.html) et le [regard](https://pixiv.github.io/three-vrm/docs/classes/three-vrm.VRMLookAt.html) natifs de three-vrm. Le regard doit pouvoir suivre une cible utile et s'en détourner ; un sourire permanent et des hochements aléatoires ne produisent pas une présence naturelle.

La bouche doit suivre la position de lecture de l'audio, pas l'arrivée du texte ni la fin de sa génération. Pour une première preuve reproductible, [Rhubarb](https://github.com/DanielSWolf/rhubarb-lip-sync) peut extraire des formes de bouche depuis un fichier audio ; son mode phonétique est prévu pour les autres langues que l'anglais. Le transfert vers le VRM et sa qualité en français restent à régler. Cette voie sur fichier ne répond pas au besoin final de dialogue continu à faible latence.

[Audio2Face-3D](https://github.com/NVIDIA/Audio2Face-3D-SDK) constitue une piste pour le flux, mais demande une adaptation du rig et un essai de consommation GPU. Il ne suffit pas de connecter ses sorties aux cinq voyelles. Une bouche simplement ouverte selon le volume reste un diagnostic, pas une synchronisation phonétique convaincante.

Les gestes liés à une phrase doivent céder la priorité à une main occupée et aux appuis. Leur annulation ne doit ni lâcher un objet ni figer brutalement une marche.

**Décision : visage natif et horloge audio commune d'abord ; essai facial plus lourd seulement après avoir identifié les limites du rig.** [Analyse détaillée](03-expression.md)

## 4. Faire du téléphone un objet réellement manipulé

La caméra POV ne demande pas nécessairement une nouvelle IA. L'infrastructure possède déjà des attachements d'objet avec position et rotation. En revanche, la prise actuelle utilise une orientation fixe de la main, et le dépôt ne permet pas de choisir librement l'orientation finale. Ces limites empêchent de cadrer naturellement avec un téléphone.

La solution proposée ajoute un objet téléphone avec sa géométrie, ses points de prise et un repère optique. Une capacité de réorientation pilote le poignet et le bras ; les doigts adoptent une prise calibrée. La caméra se calcule depuis le repère optique de l'objet effectivement tenu. Le regard peut cibler sa lentille.

Il faut conserver deux vues : observateur pour vérifier les contacts, et téléphone pour l'expérience POV. La seconde ne doit pas servir à dissimuler une main mal placée. Les deux doivent montrer le même état du corps et de l'objet, y compris après interruption ou redémarrage.

Le travail difficile est la prise, le cadrage et les transitions, pas la création d'une caméra Three.js. La première version sera une manipulation cinématique explicite. Une simulation des forces des doigts serait un chantier supplémentaire.

**Décision : étendre les capacités de main et d'objet existantes, puis tester sur plusieurs positions et orientations.** [Analyse détaillée](04-pov-camera.md)

## 5. Qualifier la voix et corriger les interruptions

La clé vocale attendue n'est pas disponible dans l'environnement inspecté. Aucun accès réel au fournisseur n'a été confirmé pendant cette recherche. La connexion ChatGPT utilisée par Hermes et l'accès Hugging Face aux modèles de mouvement ne prouvent pas cet accès vocal.

Le raccord GPT-Live actuel doit d'abord être essayé avec le compte cible. La recherche confirme qu'il repose sur une interface officielle ; aucune migration de fournisseur n'est justifiée par le seul fait que les premiers essais étaient simulés. [Délégation Live](https://developers.openai.com/api/docs/guides/live-delegation)

Il existe aussi un défaut logiciel indépendant de la clé : la coupure locale attend une transcription non vide, et la lecture ne possède pas encore de barrière suffisante contre les fragments audio tardifs. Une interruption naturelle demande une détection précoce de la parole, l'arrêt de la sortie courante, et le rejet des sorties devenues obsolètes. Le corps conserve son propre mécanisme d'arrêt.

Le relais vers Hermes annule aussi le travail actif à chaque nouveau fragment utilisateur. Il faut distinguer correction, continuation d'une phrase et simple acquiescement. Deux essais de délégation prennent environ 20 secondes ; ce temps comprend toute la boucle applicative et ses outils, avec une entrée vocale simulée. Il ne mesure ni l'inférence Astra seule ni la latence d'une conversation réelle. L'instrumentation doit montrer où ce délai se forme.

Garder Hermes comme propriétaire de la mémoire et des décisions d'action. Live est le modèle conversationnel vocal qui lui délègue ; ce n'est pas Astra avec une simple sortie sonore. Si l'on veut que chaque réponse soit rédigée par Astra, la chaîne transcription → Hermes → synthèse respecte mieux cette contrainte, avec un coût de latence à mesurer.

Après qualification du transport existant, [WebRTC Live](https://developers.openai.com/api/docs/guides/voice-webrtc?api=live) constitue la cible pour l'avatar dans le navigateur : un seul flux joué et une seule horloge pour le son et les lèvres, Hermes restant côté serveur. Ce changement ne dispense pas de vérifier l'écho et les coupures avec le vrai microphone.

**Décision : conserver la voie Live/Hermes, réparer l'interruption, puis qualifier le dialogue réel. Utiliser la chaîne sur fichier pour isoler les défauts.** [Analyse détaillée](05-voice.md)

## Ordre de développement recommandé

| Étape | Livrable observable | Condition de passage |
|---|---|---|
| 1. Mesures communes | Chronologie du mouvement et de l'audio, refus et mémoire GPU | Chaque attente et chaque coupure sont attribuables à une étape |
| 2. Corps continu | ARDY avec historique, réserve validée et changements de consigne | Pas de retour à une ancienne intention, appuis et transitions acceptables |
| 3. Marche fiable | Comparaison des corrections et contrôle des intersections | Batterie réservée satisfaisante ; sinon essai de locomotion par animations |
| 4. Visage et voix | Regard, expressions et lèvres suivant le lecteur audio ; interruption corrigée | Synchronisation mesurée et absence de reprise d'une sortie invalidée |
| 5. Téléphone | Prise orientée, réorientation, vue optique liée à l'objet | Contact crédible dans les deux vues et restauration cohérente |
| 6. Intégration | Prises continues avec consignes variées et interruptions | Naturel jugé sur le rendu réel, sans masquer les échecs par le montage |

Le visage sur fichier audio et la correction de l'interruption peuvent avancer pendant le chantier moteur. La caméra peut être préparée sur un corps immobile. Leur validation finale dépend du corps continu. Aucun calendrier global fiable ne découle de cette seule recherche ; les annexes donnent des estimations d'ingénierie, à réviser après les premiers essais.

## Matériel et choix à différer

La machine inspectée possède une RTX 4080 de 16 Go, environ 32 Go de RAM et un Ryzen 7 5800X3D. L'essai moteur existant mesure environ 14,58 Gio pour l'encodeur et 0,87 Gio pour ARDY : la marge GPU est étroite. Ce sont des mesures d'un essai antérieur, pas la consommation instantanée ni une preuve de cohabitation avec d'autres modèles. [Mesures et versions](../decisions/001-motion-stack.md)

Conserver les traitements faciaux légers sur CPU pour le premier essai. Avant Audio2Face ou IsaacLab, mesurer une exécution isolée puis leur concurrence avec le mouvement. Aucun achat de matériel ni entraînement massif n'est recommandé avant ces mesures.

Le tarif Live publié au jour de la recherche est de 0,05 USD par minute de session, soit 3 USD par heure continue pour cette partie vocale seule. Les appels du backend et les outils sont distincts ; ce n'est pas un budget total de fonctionnement d'Ariane. [Tarif officiel](https://developers.openai.com/api/docs/models/gpt-live-1)

Les contrôleurs physiques préentraînés peuvent éviter de partir de zéro, mais leur corps, leurs données et leurs conditions d'exécution doivent correspondre au projet. Une démonstration NVIDIA n'est pas une garantie pour notre VRM.

## Comment vérifier le résultat

Les critères suivants sont proposés pour les prochains essais ; ils ne sont pas déjà atteints :

- Déplacements et transitions sur plusieurs positions, caps et interruptions, avec un ensemble de calibration distinct des cas de validation. Comparer d'abord dans la limite actuelle de deux mètres ; les trajets plus longs constituent une extension séparée.
- Mesures aux poses intermédiaires : appuis, intersections, longueurs d'os et attachement main/objet. Mesurer aussi vitesse et accélération aux raccords, pas seulement l'écart de position.
- Pour la continuité, dix minutes sans épuisement de la réserve sur les mouvements acceptés, en publiant aussi les refus. Un rejet n'est pas supprimé du compte rendu.
- Pour l'audio et le visage, mesurer le décalage sur une capture réelle. Les seuils d'essai proposés dans l'annexe sont notamment un p95 inférieur à 80 ms pour la synchronisation audiovisuelle et aucune reprise de génération invalidée.
- Capturer des prises continues de 30–60 secondes, avec pieds et mains inspectables dans la vue observateur, et des gros plans POV. Varier les demandes ; conserver aussi les mauvaises prises.
- L'utilisateur juge la naturalité. Des tests logiciels verts, 60 images par seconde ou une seule belle vidéo ne suffisent pas à l'établir.

Le prochain résultat décisif est un corps qui enchaîne des consignes variées de façon fluide tout en restant cohérent avec le monde. Le film de présentation vient après cette preuve.
