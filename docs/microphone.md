# Entrée vocale locale et interruptions

Étape T11 du 16 septembre 2026. Le raccord expérimental utilise le détecteur
Silero v5 dans le navigateur, Faster Whisper small sur CPU, le même hôte
Hermes/Luna que le texte, puis la référence VoxCPM2 approuvée. Ce choix ne
valide pas l'ancien adaptateur GPT-Live avec un fournisseur réel.

## Contrat

Le microphone s'ouvre seulement après activation dans l'interface. Une capture
déclenche d'abord une coupure locale et `input_start`. Avant son acquittement,
le serveur clôt durablement le tour Hermes précédent ; ses futurs outils sont
refusés. Le nettoyage du processus Hermes reste dans le thread propriétaire.
L'action corporelle déjà acceptée continue. Seul l'arrêt explicite demande
aussi l'arrêt du corps.

`input_audio` transporte un segment PCM16 mono 16 kHz, limité à 12 secondes,
avec les identifiants de capture et de session. Le serveur admet un travail ASR
en cours et un segment en attente. Une nouvelle prise de parole invalide le
résultat précédent ; un rejeu identique est sans effet et un autre audio sous
le même identifiant est refusé. Le PCM n'est pas archivé par ce raccord ; la
transcription rejoint le journal conversationnel habituel.

Une capture vide, un bruit trop court, une panne, un délai dépassé ou un
résultat périmé ne lance pas Hermes. Le texte reste utilisable. Les délais
sont bornés : chargement ASR 60 s, inférence 30 s, capture serveur 18 s et
attente totale de transcription 40 s. Ce sont des bornes d'échec, pas des
objectifs de latence. Chaque prise de parole obtient une réponse ; elle ne
réactive pas automatiquement l'improvisation de 60 secondes.

Le détecteur demande au navigateur l'annulation d'écho et la suppression du
bruit. Aucune efficacité acoustique n'est déduite de ces options. Les pistes
sont libérées à la désactivation, à la fermeture, à l'arrêt et aux erreurs.
Les versions, commandes et licences figurent dans le
[guide de lancement](../experiments/voice/realtime/README.md#entrée-vocale-locale-facultative).

## Reconnaissance réelle sur CPU

Environnement Windows x86_64, Python 3.13.12, Ryzen 5800X3D ; Faster Whisper
1.2.1, CTranslate2 4.8.2, int8, quatre threads, français, beam size 1.
Les 26 dépendances résolues sont épinglées et `uv pip check` réussit.

| Variante | Révision | Observation |
|---|---|---|
| Base | `ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66` | 0,50–0,59 s pour trois extraits de 4,64–5,92 s ; erreurs de mots et de sens. Non retenue |
| Small | `536b0662742c02347bc0e980a01041f333bce120` | 1,80–1,87 s sur les mêmes extraits ; deux transcriptions lexicalement fidèles, premier extrait encore fortement déformé |
| Small, sept extraits réservés | Même modèle et réglages figés | 1,72–1,95 s pour 4,64–7,04 s d'audio ; quatre transcriptions lexicalement fidèles, omissions sur deux et mauvaise liaison « piste honnête » sur une |

Les durées mesurent l'inférence, pas la fin de parole jusqu'au son de réponse.
Le silence de deux secondes produit une transcription vide dans les deux
variantes. Les dix extraits viennent de WAV Vox déjà générés : leur texte de
génération n'est pas une transcription humaine de référence. Cette comparaison
justifie un choix expérimental de small ; elle n'établit ni un taux d'erreur
général ni la qualité sur le microphone utilisateur.

Archives locales : `asr-qualification-01`, `asr-qualification-small-01` et
`asr-qualification-small-holdout-01`, avec sorties brutes, durées et fermeture
du processus. Le manifeste du snapshot small conserve les tailles et SHA-256 ;
`model.bin` vaut `3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671`.

## Vérifications de concurrence et du navigateur

Les tests CPU couvrent l'invalidation durable, les commandes anciennes,
les captures et réponses périmées, les doublons, la saturation, les délais,
le microphone absent et le secours texte. Les tests du worker utilisent aussi
de vrais sous-processus pour les crashs, réponses invalides, fermetures et la
destruction des descendants Windows.

La relecture parallèle a reproduit huit courses : publication d'anciens
événements Vox sous un nouvel identifiant de session, échec Hermes écrasant
l'écoute, ancien minuteur arrêtant le corps et statut d'arrêt tardif. Les
gardes et publications sont désormais atomiques. La clôture du processus
Hermes reste hors verrou ; un retour tardif est ignoré. La publication erronée
est prouvée par tests, pas une reprise audible : le lecteur possède aussi sa
propre garde par identifiant de parole.

Le premier essai navigateur avec une source audio synthétique a échoué avant
l'envoi : les fonctions natives de minuteur recevaient un mauvais `this`.
Leurs appels sont corrigés, et le nettoyage reste garanti même si l'annulation
échoue. Ce défaut a été découvert avec le vrai détecteur WASM, après réussite
des premiers doubles de test ; l'essai échoué reste dans les archives.

L'essai numérique suivant traverse effectivement le MediaStream synthétique,
Silero WASM/AudioWorklet, small CPU, Hermes résident et Vox, jusqu'aux reçus du
lecteur. Il conserve deux tours dans la session `43139cf27779`, avec une
interruption de la première lecture après 1,48 s puis une deuxième lecture
complète de 4,48 s, sans sous-alimentation PCM. L'ancien identifiant de parole
ne redémarre pas.

Les premiers sons de réponse arrivent 7,21 et 10,01 s après la fin de chaque
WAV source ; la transcription prend 2,30 et 1,79 s, Hermes 3,47 et 6,92 s.
Des tests CPU s'exécutaient simultanément : il s'agit d'observations de cette
session, pas d'un benchmark isolé. Le début du second WAV précède de 790 ms
la demande de coupure ; l'appel de mute après détection prend 0,3 ms et
l'acquittement local arrive en 5,2 ms. La mesure de mute est un appel logiciel,
pas la mesure acoustique d'un haut-parleur.

Le prébuffer de capture initial de 320 ms tronquait les premiers mots du
second extrait, que l'ASR avait correctement reconnus sur le WAV complet.
Il passe à 800 ms ; le plafond de capture après détection passe à 11,1 s pour
garder le segment total sous 12 s. Cela conserve plus de contexte sonore sans
prétendre accélérer la détection. Le premier essai complet reste archivé dans
`microphone-digital-01/browser-19644cfd.json` et ses observations serveur.

Le rejeu du même extrait avec 800 ms conserve ensuite toute la phrase :
transcription lexicalement exacte, 1,743 s d'inférence, réponse lue 6,14 s
après la fin du WAV et lecture complète de 4,96 s, sans sous-alimentation.
La ligne « Vous : … » affiche le texte reconnu ; aucun `input_cancel` tardif
n'est envoyé après succès. Preuves : `browser-f35615fa.json` et
`after-prepad-state.json` dans la même archive. Ce rejeu corrige le cas observé,
sans constituer une évaluation indépendante de toutes les voix.

Pendant cette session, un segment de présence ARDY est refusé par le recalage
VRM : la correction verticale change de 26,17 mm en 50 ms lors du passage de
la semelle gauche à la pointe, au-delà de la limite de 15 mm par image. La
pose initiale était exactement conservée ; le segment refusé n'est pas joué.
La présence se suspend, le corps reste valide et une nouvelle activation
reprend depuis sa pose observée. Trois préparations réussies sont ensuite
constatées ; cela ne supprime pas la limite géométrique. Le message technique
« Cannot initialize » ne signifie pas que le corps entier a perdu son état.
Le rapport est dans `session-43139cf27779/world/appearance/8b247649239d4987b27b074dd7e45dfe/measurement.json`.
Il faut instrumenter cette transition pour corriger le recalage ; aucun seuil
n'est assoupli pour présenter cet essai vocal comme une réussite motrice.

La fin d'une réponse unique suspend maintenant la gestuelle de parole, sans
annuler les actions corporelles acceptées. Elle ne laisse plus cette génération
tourner pendant l'attente silencieuse d'un nouveau message.

Validation du code : 647 tests du socle réussis, 2 ignorés ; 249 tests de la
scène et 7 sous-tests réussis ; 39 tests navigateur réussis et 2 vérifications
de médias privés facultatives ignorées. Ces nombres ne qualifient pas le
matériel acoustique.

## Critères encore ouverts

L'acoustique réelle, l'écho, le microphone choisi par l'utilisateur et les
interruptions aux différentes phases doivent être essayés sur son matériel.
Les mesures numériques ne remplacent pas ce test. Le coût monétaire par tour
Hermes n'est pas exposé par l'authentification Codex utilisée ; aucun coût nul
n'est revendiqué. ASR et TTS s'exécutent localement, sans API vocale payante,
mais consommation et amortissement matériel ne sont pas mesurés.

T11 reste ouvert tant que ces critères ne sont pas établis. Le budget
d'initiative persistant de T12 reste distinct de la boucle d'essai vocale.
