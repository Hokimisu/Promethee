# Avancement vérifié

Ce registre distingue le code livré des intégrations réellement vérifiées. Les critères de référence restent dans le [plan d'implémentation](implementation-plan.md).

| Ticket | État | Preuves |
|---|---|---|
| T00 | Vérifié sur CPU | Python 3.13.12, uv 0.12.5 ; 22 tests initiaux, lint, format et construction réussis ; pause/reprise dans deux processus |
| T01 | Implémenté et vérifié sur CPU | Commandes `catalog` et `act` ; 29 tests passent, dont les tests en sous-processus de `tests/test_cli_actions.py` ; lint, format et construction passent |
| T02 | Essai réel terminé ; ARDY Core et Viser retenus | Installation neuve reconstruite, génération réelle, changement de texte et contrainte de vitesse ; cas réservés 301–303 conformes aux critères de racine. Conventions, latences, provenance et limites dans la [décision](decisions/001-motion-stack.md) et [l'essai reproductible](../experiments/motion/README.md). Contacts physiques non validés |
| T03 | Implémenté et vérifié sur CPU | Schéma v2, migration avec sauvegarde vérifiée, origine immuable et révisions ; 37 tests passent |
| T04 | Implémenté et vérifié sur CPU | Suivi séparé, observation atomique, révision, `busy`, doublons et provenance du pilote ; contrôleur factice explicite |
| T05 | Implémenté et vérifié sur CPU | Annulation, bail exclusif, réconciliation et coupures réelles de processus ; 60 tests passent, lint, format et construction réussis |
| T06 | Implémenté et vérifié avec le vrai squelette | Viser en lecture seule, deux dispositions, mise à jour d'un objet, lecture/scrutation d'un NPZ ARDY, contrôle d'échelle et de rotation ; 69 tests CPU passent. [Guide de rendu](rendering.md) |
| T07 | En cours | Pilotage ARDY, arrêt et reprise réels. Projection des appuis Core en marche ; séries nouvelles 15–16 : trois déplacements sur quatre et trois postures sur quatre terminent. Chaque trajet accepté garde un contact géométrique sur 120 images sur 120. Fiabilité, inclinaison du corps et appuis VRM restent à résoudre. [Mesures et limites](motion-validation.md) |
| T08 | Interactions cinématiques implémentées et vérifiées | Doudou et balle, plusieurs positions, géométries et orientations ; prise, dépôt, impossibilités, annulation avant/après contact et restauration. [Contrôleur](spatial-objects.md), [portée VRM](avatar-arm-reach.md) et [session en direct](live-avatar.md). Ni doigts physiques ni appuis validés |
| T09 | Hôte texte implémenté ; Astra à raccorder | Cinq outils du monde, quatre outils mémoire optionnels ; historique natif persistant, correction et délai maximal gérés avec fermeture des processus. Commande réelle ARDY et retransmission vérifiées séparément. Qualification du vrai Hermes avec fournisseur de test local. Accès OpenAI essayé : HTTP 401. [Configuration et limites](hermes-setup.md) |
| T10 | Mémoire sourcée implémentée et vérifiée | Recherche dans les notes Markdown, sources consultables, corrections liées, distinction du monde actuel, exclusion des qualifications et préservation des éditions. Tests CPU, vrai transport MCP et vrai Hermes avec fournisseur local ; aucune qualité de raisonnement Astra ni revue visuelle Obsidian revendiquée. [Contrat et qualification](memory.md) |
| T11 | Diagnostic vocal implémenté ; qualification réelle à faire | Micro à la demande → même Hermes → synthèse. Interruptions testées ; vrai Hermes et SDK audio avec fournisseurs/périphérique simulés. Aucun microphone ni fournisseur réel validé ; GPT-Live reste à raccorder. [Mode et limites](voice.md) |
| T12 | Initiative bornée implémentée ; observations Astra à faire | Budget et pause persistants, regroupement d'événements, réservation atomique et tours obsolètes testés. Un réveil dans le vrai Hermes avec fournisseur local ; aucune initiative personnelle activée. [Contrat et limites](initiative.md) |
| T13 | À réaliser selon limite mesurée | Aucun entraînement ni connecteur supplémentaire revendiqué |

Les journaux de test et données locales restent dans `.local/` et ne sont pas publiés.

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
