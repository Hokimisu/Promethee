# Avancement vérifié

Ce registre distingue le code livré des intégrations réellement vérifiées. Les critères de référence restent dans le [plan d'implémentation](implementation-plan.md).

L'[audit des critères ouverts](completion-audit.md) rapproche les archives réelles
et le code courant. Les comptes rendus sous le tableau sont chronologiques :
leurs limites décrivent la version de chaque essai, pas nécessairement la dernière.

| Ticket | État | Preuves |
|---|---|---|
| T00 | Vérifié sur CPU | Python 3.13.12, uv 0.12.5 ; 22 tests initiaux, lint, format et construction réussis ; pause/reprise dans deux processus |
| T01 | Implémenté et vérifié sur CPU | Commandes `catalog` et `act` ; 29 tests passent, dont les tests en sous-processus de `tests/test_cli_actions.py` ; lint, format et construction passent |
| T02 | Essai réel terminé ; ARDY Core et Viser retenus | Installation neuve reconstruite, génération réelle, changement de texte et contrainte de vitesse ; cas réservés 301–303 conformes aux critères de racine. Conventions, latences, provenance et limites dans la [décision](decisions/001-motion-stack.md) et [l'essai reproductible](../experiments/motion/README.md). Contacts physiques non validés |
| T03 | Implémenté et vérifié sur CPU | Schéma v2, migration avec sauvegarde vérifiée, origine immuable et révisions ; 37 tests passent |
| T04 | Implémenté et vérifié sur CPU | Suivi séparé, observation atomique, révision, `busy`, doublons et provenance du pilote ; contrôleur factice explicite |
| T05 | Implémenté et vérifié sur CPU | Annulation, bail exclusif, réconciliation et coupures réelles de processus ; 60 tests passent, lint, format et construction réussis |
| T06 | Implémenté et vérifié avec le vrai squelette | Viser en lecture seule, deux dispositions, mise à jour d'un objet, lecture/scrutation d'un NPZ ARDY, contrôle d'échelle et de rotation ; 69 tests CPU passent. [Guide de rendu](rendering.md) |
| T07 | Vérifié dans le périmètre cinématique qualifié | Dernier essai indépendant : deux postures et un déplacement terminés, un déplacement refusé ; contact géométrique sur les 120 poses de chaque séquence acceptée. Données terminales, observations et événements concordent. Panne du contrôleur préparé à l'image 10 : checkpoint et rendu restaurés, action interrompue sans rejeu. [Audit et limites](completion-audit.md#t07--corps-et-résultat-observé) |
| T08 | Interactions cinématiques implémentées et vérifiées | Doudou et balle, plusieurs positions, géométries et orientations ; prise, dépôt, impossibilités, annulation avant/après contact et restauration. [Contrôleur](spatial-objects.md), [portée VRM](avatar-arm-reach.md) et [session en direct](live-avatar.md). Ni doigts physiques ni appuis validés |
| T09 | Vérifié avec Astra et ARDY réels | Authentification ChatGPT native de Hermes, conversation sans action, lecture du monde, historique après redémarrage, posture exécutée et résultat observé. Après interruption pendant le mouvement, le nouveau tour retrouve l'annulation sans relancer l'action. Refus d'un objet absent. [Configuration, essais et limites](hermes-setup.md) |
| T10 | Mémoire sourcée vérifiée sur CPU et avec Astra | Six appels réels dans deux mondes : recherche vide, proposition, correction retrouvée avec l'ancien terme, source relue et distinction du monde actuel. Deux notes dans le premier coffre, zéro dans le second, aucune action ; coffres ensuite exclus comme qualification. Retrait d'objet et contenus non fiables couverts par tests CPU ; pas de revue visuelle Obsidian. [Contrat et qualification](memory.md) |
| T11 | Raccord Live/Hermes implémenté ; audio réel à qualifier | SDK Live isolé et vrai Astra testés avec serveur vocal simulé, historique partagé au démarrage, usage final contrôlé. Mode fichier et périphériques explicites avec buffers bornés ; erreurs et coupure locale testées sans matériel audio. Migration v11 pour les comptes rendus du diagnostic. Accès vocal réel, interruption acoustique sans parole tardive, latence et coût restent à qualifier. [Raccord et limites](live-integration.md), [configuration](live-file-session.md) |
| T12 | Initiative textuelle vérifiée avec Astra ; dépendance vocale ouverte | Deux séries réelles : mondes sans historique et après sollicitation, contrôleur ARDY actif puis retiré, pause après redémarrage et budgets épuisés. Aucun appel supplémentaire ni action corporelle. Référence active corrigée après fin de tour ; 363 tests passent. Aucune initiative personnelle activée ; T11 reste à qualifier. [Contrat et limites](initiative.md) |
| T13 | Appuis corrigés et génération par blocs intégrée ; naturalité ouverte | [Recherche](research/humanlike-solutions-2026-09-15.md), [correction talon/pointe](avatar-foot-roll.md) et [mode continu expérimental](continuous-motion.md) : historique et futur séparés, génération pendant la lecture, annulation réelle conservant exactement la pose. Deux postures réussissent dans la série indépendante, deux déplacements échouent et cinq attentes persistent. Aucun entraînement ni connecteur supplémentaire revendiqué |

Les journaux de test et données locales restent dans `.local/` et ne sont pas publiés.

Le [processus GPT-Live](live-integration.md#processus-de-transport) utilise un
environnement SDK séparé. Cinq essais locaux du vrai processus vérifient
l'échange PCM, le retour au même ID de délégation, le rejet d'une entrée invalide,
la coupure réseau et les bilans finaux absents ou incomplets. Il ne se reconnecte
pas automatiquement. Le [raccord de délégation](live-integration.md#délégation-au-même-hôte-hermes)
transmet désormais des fragments sourcés au même Hermes. Deux appels Astra réels
sur événements Live simulés distinguent une affirmation vocale d'une action
confirmée ; zéro exécution. La [boucle sur fichier audio](live-file-session.md)
est exécutable : un essai de 60 s relie le vrai SDK à Astra, avec serveur Live
et PCM simulés, une délégation, un bilan final et zéro action. Les périphériques
et la voix du service distant restent à raccorder et à qualifier.
Une expiration imposée par le serveur local ferme désormais aussi le vrai SDK
proprement : bilan conservé, commandes en attente abandonnées, zéro appel Hermes.
Les erreurs du processus restent distinctes d'une fermeture confirmée.
Les consignes de voix et une vue sourcée du contexte Hermes sont maintenant
transmises au démarrage. Sur une copie de qualification, le vrai SDK reçoit
l'historique antérieur sans le déclarer entendu ; une délégation sans nouvelle
transcription utilisateur ne relance aucun travail. Les échanges Live non
délégués ne sont pas encore réintégrés après panne.

La branche [codex/execution-receipts-after-interruption](https://github.com/Hokimisu/Promethee/tree/codex/execution-receipts-after-interruption)
rend les huit résultats d'exécution les plus récemment mis à jour consultables
avec le monde. Le nouveau tour Astra peut ainsi retrouver une action dont
l'ancien tour interrompu n'a pas conservé l'identifiant. Les deux essais réels
et leurs relectures VRM sont décrits dans le [guide Hermes](hermes-setup.md).
Vérifications : 355 tests passent, deux sont ignorés ; lint, format et
construction du paquet réussis. La voix réelle et la qualification complète
des mouvements restent ouvertes.

Les paragraphes suivants conservent les étapes de qualification antérieures ;
leurs limites décrivent chaque essai à sa date. Les guides liés documentent
les corrections et essais ultérieurs.

Les [poses d'apparence préparées](avatar-foot-contact.md#poses-préparées-avant-lecture)
peuvent être exportées et rejouées sans recalculer l'adaptation. Sur 519 images
de calibration, les appuis et la cible de main sont conservés après passage
par JSON ; le déplacement dépassant 5 cm reste refusé sans export. Ce chemin
reste hors session. Le [chargeur Python](avatar-foot-contact.md#vérification-python-des-poses-préparées)
vérifie désormais leur provenance, les rotations non adaptées et les cibles de
main. Le [préparateur annulable](avatar-foot-contact.md#préparation-annulable-en-arrière-plan)
est vérifié hors session avec le vrai VRM et deux phases d'annulation. Son
raccord au pilote reste à faire. Le [stockage de la pose visible](avatar-foot-contact.md#sauvegarde-de-la-pose-visible)
est maintenant couvert par le schéma 10, les tests de rollback et une
réouverture sur une copie de session contenant une pose VRM réelle.

La [comparaison des réglages ARDY](motion-sampling.md) sur quatre requêtes
archivées n'a pas identifié d'amélioration générale. Le checkpoint est limité
à dix étapes de génération ; changer le guidage peut réduire un saut de bras
mais aggraver l'inclinaison ou faire échouer un déplacement auparavant accepté.
Le pilote conserve son réglage, sans nouvelle tentative cachée.

La [mesure du maillage des chaussures](avatar-foot-contact.md) retrouve zéro
image en contact VRM sur trois séquences où Core garde un appui sur 120 images
sur 120. Le lecteur et un outil local permettent désormais de vérifier cette
différence ; sa correction reste nécessaire.

Un [essai d'ancrage VRM hors session](avatar-foot-contact.md#essai-dadaptation-hors-session)
obtient un contact sur toutes les images d'un déplacement et d'une posture de
calibration. Un autre déplacement dépasse encore la correction autorisée de
5 cm. Le raccord au contrôleur et les essais indépendants restent à réaliser.

La [portée des bras après correction de hauteur](avatar-arm-reach.md#portée-après-adaptation-de-hauteur)
est vérifiée sur 1 955 poses VRM issues des sept parcours objets. Le calcul CPU
peut désormais recevoir un décalage vertical explicite et borné, sans modifier
la cible observée de la main. Le rendu en direct conserve encore le décalage nul.

L'[apparence VRM](avatar-rendering.md) dispose d'une lecture animée en textures,
vérifiée sur un déplacement et une posture ARDY. Les hanches sont conservées,
mais les chaussures flottent de 1 à 4 cm sur ces essais ; les appuis ne sont
pas validés. Une [session en direct](live-avatar.md) utilise maintenant le même
rendu pour les commandes manuelles, sans nouveau comportement d'agent.

T06 est livré sur la branche [codex/world-viewer](https://github.com/Hokimisu/Promethee/tree/codex/world-viewer). Le rendu optionnel a été lancé sous Windows 11/Python 3.13.12 et inspecté dans le navigateur intégré : lecture et pause d'une séquence de 120 poses, déplacement d'objet visible à la révision 6, seconde disposition avec pose neutre tournée de 90°, puis réouverture. Les contrôles sur Core confirment 27 articulations, échelle de 1,684 m, conservation exacte des positions NPZ et absence d'écriture SQLite. Les objets restent des repères explicitement sans asset ; aucune assise, prise ou collision n'est revendiquée.

T02 est livré sur la branche [codex/motion-qualification](https://github.com/Hokimisu/Promethee/tree/codex/motion-qualification). Les scripts reproduisent les environnements séparés, les poids épinglés, le service d'encodage et les mesures brutes/post-traitées. Les erreurs de coordonnées initiales restent conservées et sont rejetées par le vérificateur ; les trois cas réservés passent. L'installation neuve génère également trois séquences de 40 poses. Le rendu officiel a été inspecté, mais l'analyse détaillée des contacts, l'annulation et le raccord au monde restent dans T06–T08.

Pour T02, la copie [NousResearch/Meta-Llama-3-8B-Instruct](https://huggingface.co/NousResearch/Meta-Llama-3-8B-Instruct/tree/53346005fb0ef11d3b6a83b12c895cca40156b6c) est épinglée à `53346005fb0ef11d3b6a83b12c895cca40156b6c`. Le 15 septembre 2026, l'API Hugging Face annonce `gated: false` et les quatre fichiers Safetensors répondent HTTP 200 sans jeton. Leurs SHA-256 annoncés correspondent à ceux du dépôt `meta-llama/Meta-Llama-3-8B-Instruct`. La licence Llama 3 reste applicable. Les adaptateurs MNTP et supervised de McGill doivent tous deux être conservés ; le changement de provenance des poids ne suffit pas à valider le chargement ni l'inférence ARDY.

T00–T01 sont livrés sur la branche [codex/manual-world-control](https://github.com/Hokimisu/Promethee/tree/codex/manual-world-control). Le pilotage reste logique et instantané.

T03 est livré sur la branche [codex/world-provenance](https://github.com/Hokimisu/Promethee/tree/codex/world-provenance). Les essais couvrent conservation du plan suspendu et des rejets, rollback après panne, origine des exports, refus d'accès agent aux fixtures/historiques et révisions concurrentes.

T04–T05 sont livrés sur la branche [codex/body-execution](https://github.com/Hokimisu/Promethee/tree/codex/body-execution). `execution.py`, la migration v3 et les exports distinguent intention, progression et résultat confirmé. Les tests de récupération coupent un sous-processus avant envoi, après envoi, pendant la progression et pendant la transaction finale ; aucune action n'est automatiquement réémise. La documentation donne le chemin de réconciliation. Vérifications : `uv run pytest -q` (répertoire temporaire neuf dédié sous Windows), `ruff check`, `ruff format --check`, `uv build`, Python 3.13.12. Ce travail prépare T07 ; le mouvement réel et son format articulaire dépendent encore de T02–T06.
