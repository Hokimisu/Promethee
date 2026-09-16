# Corps et bouche pendant la parole

Qualification locale du 16 septembre 2026, suite au signalement d'un avatar
immobile pendant l'essai vocal de 60 secondes.

## Causes observées

Le contrôleur continu prolongeait uniquement une action explicite. Son
initialisation conservait la première pose ; en l'absence de commande Astra,
la boucle republiait cette pose. Une fréquence de publication de 20 Hz
n'attestait donc aucun mouvement.

Le VRM possède les visèmes `aa`, `ih`, `ou`, `ee`, `oh`. Le lecteur PCM mesurait
l'amplitude du dernier bloc de 128 échantillons plutôt que celle de toute la
fenêtre de lecture. Le gain d'ouverture rendait aussi les passages doux presque
invisibles. Le correctif local utilise tous les échantillons effectivement joués,
une ouverture plus visible et une fermeture au silence, à la suspension ou à
l'arrêt. Il s'agit d'une ouverture pilotée par l'amplitude, pas de phonèmes.

## Changements et vérifications CPU

- `ControllerHandle.observe_idle(observation)` valide et persiste une observation
  hors exécution, sans fabriquer une action Astra ni déclarer le corps arrêté.
  Le bail doit être valide ; une action acceptée ou en cours reste prioritaire.
  Les 13 nouveaux tests et 32 tests existants d'exécution, récupération et
  apparence passent.
- Le correctif local de bouche passe 16 tests frontend, dont chargement du vrai
  VRM, déformation de ses primitives et lecture d'un WAV Vox existant.
- La qualification locale utilise un prompt de gestuelle réellement encodé avec
  LLM2Vec/Meta-Llama-3-8B-Instruct et ses adaptateurs ARDY qualifiés :
  `A person stands in place and speaks with natural expressive hand gestures.`
  Ce prompt est une proposition expérimentale, pas une garantie de qualité.

Les scripts, caches, voix et données de session restent sous
`.local/realtime-voice-01/`. Ce raccord local n'est pas une capacité livrée par
la commande de lancement publique.

## Limite de coordination identifiée

La révision du monde change avec les observations corporelles. Pendant une
présence continue, une révision lue par Astra peut être périmée au moment de
soumettre une action. Le contrôle strict de révision reste inchangé : aucun
remplacement silencieux de la révision fournie par le modèle.

Une proposition non implémentée est un rendez-vous borné lors de la soumission :
suspendre la présence, confirmer sa dernière observation, rendre un refus et un
snapshot récent si nécessaire, puis laisser Astra produire une nouvelle
enveloppe. Une séparation durable des révisions de décision et d'observation
demande un contrat explicite et des tests de concurrence.

La réussite d'une génération, d'un test CPU ou d'une mesure de fréquence ne
qualifie ni la fluidité perçue, ni la cohérence sémantique gestes/dialogue, ni un
équilibre physique. Les résultats du test réel doivent être ajoutés séparément.

## Essai réel de 60 secondes

Le serveur local, ARDY, VoxCPM2 et le navigateur ont exécuté un essai complet.
Le contexte d'essai était une conversation amicale sans déplacement demandé ;
les répliques étaient improvisées par Astra. Aucun clip de mouvement archivé
n'a été joué. La présence utilise une tolérance de placement de 1 m autour de
son ancre initiale, conformément au choix utilisateur ; les contrôles de
continuité et de contacts restent inchangés. Les 60 tests ciblés présence et
contrôleur cinématique passent.

Le relevé `presence-trial-14d71139/report.json` sous le dossier local conserve :

- 810 poses d'apparence distinctes, aucune erreur de présence ;
- premier geste après 2,76 s de préparation ; ensuite, plus longue pose
  inchangée mesurée à environ 0,43 s ;
- trois répliques entièrement lues, 49,76 s de parole dans la fenêtre de 60 s,
  aucune sous-alimentation du lecteur audio ;
- ouverture de bouche mesurée entre 0,48 et 0,87 pendant un échantillon de
  parole, puis 0 après l'arrêt automatique.

La scène affichée montre les gestes des mains et les changements de posture.
La génération est maintenant raccordée à la présence conversationnelle, mais
les gestes ne sont pas encore choisis selon le sens précis de chaque phrase.
Il subsiste de petites attentes entre horizons de mouvement et entre répliques.
Ce test ne valide pas le timbre ou le jeu émotionnel, qui restent à l'écoute
de l'utilisateur. Le contrôleur local expose ses erreurs au lieu de les
présenter comme une immobilité volontaire.
