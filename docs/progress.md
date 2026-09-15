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
| T07 | En cours | Pilotage ARDY, postures, arrêt et reprise réels ; correction des jambes et distinction contact/proximité. Les séries 09–10 terminent un déplacement sur quatre et deux postures sur quatre. Les appuis restent insuffisants, même sur le déplacement accepté. [Mesures et limites](motion-validation.md) |
| T08 | À réaliser | Interactions corporelles avec les objets non livrées |
| T09 | Hôte texte implémenté ; Astra à raccorder | Cinq outils du monde, quatre outils mémoire optionnels ; historique natif persistant, correction et délai maximal gérés avec fermeture des processus. Commande réelle ARDY et retransmission vérifiées séparément. Qualification du vrai Hermes avec fournisseur de test local. Accès OpenAI essayé : HTTP 401. [Configuration et limites](hermes-setup.md) |
| T10 | Mémoire sourcée implémentée et vérifiée | Recherche dans les notes Markdown, sources consultables, corrections liées, distinction du monde actuel, exclusion des qualifications et préservation des éditions. Tests CPU, vrai transport MCP et vrai Hermes avec fournisseur local ; aucune qualité de raisonnement Astra ni revue visuelle Obsidian revendiquée. [Contrat et qualification](memory.md) |
| T11–T13 | À réaliser | Aucune intégration réelle revendiquée |

Les journaux de test et données locales restent dans `.local/` et ne sont pas publiés.

L'[apparence VRM](avatar-rendering.md) dispose d'une lecture animée en textures,
vérifiée sur un déplacement et une posture ARDY. Les hanches sont conservées,
mais les chaussures flottent de 1 à 4 cm sur ces essais ; les appuis ne sont
pas validés. Cette vue reste en lecture seule, sans nouveau comportement d'agent.

T06 est livré sur la branche [codex/world-viewer](https://github.com/Hokimisu/Promethee/tree/codex/world-viewer). Le rendu optionnel a été lancé sous Windows 11/Python 3.13.12 et inspecté dans le navigateur intégré : lecture et pause d'une séquence de 120 poses, déplacement d'objet visible à la révision 6, seconde disposition avec pose neutre tournée de 90°, puis réouverture. Les contrôles sur Core confirment 27 articulations, échelle de 1,684 m, conservation exacte des positions NPZ et absence d'écriture SQLite. Les objets restent des repères explicitement sans asset ; aucune assise, prise ou collision n'est revendiquée.

T02 est livré sur la branche [codex/motion-qualification](https://github.com/Hokimisu/Promethee/tree/codex/motion-qualification). Les scripts reproduisent les environnements séparés, les poids épinglés, le service d'encodage et les mesures brutes/post-traitées. Les erreurs de coordonnées initiales restent conservées et sont rejetées par le vérificateur ; les trois cas réservés passent. L'installation neuve génère également trois séquences de 40 poses. Le rendu officiel a été inspecté, mais l'analyse détaillée des contacts, l'annulation et le raccord au monde restent dans T06–T08.

Pour T02, la copie [NousResearch/Meta-Llama-3-8B-Instruct](https://huggingface.co/NousResearch/Meta-Llama-3-8B-Instruct/tree/53346005fb0ef11d3b6a83b12c895cca40156b6c) est épinglée à `53346005fb0ef11d3b6a83b12c895cca40156b6c`. Le 15 septembre 2026, l'API Hugging Face annonce `gated: false` et les quatre fichiers Safetensors répondent HTTP 200 sans jeton. Leurs SHA-256 annoncés correspondent à ceux du dépôt `meta-llama/Meta-Llama-3-8B-Instruct`. La licence Llama 3 reste applicable. Les adaptateurs MNTP et supervised de McGill doivent tous deux être conservés ; le changement de provenance des poids ne suffit pas à valider le chargement ni l'inférence ARDY.

T00–T01 sont livrés sur la branche [codex/manual-world-control](https://github.com/Hokimisu/Promethee/tree/codex/manual-world-control). Le pilotage reste logique et instantané.

T03 est livré sur la branche [codex/world-provenance](https://github.com/Hokimisu/Promethee/tree/codex/world-provenance). Les essais couvrent conservation du plan suspendu et des rejets, rollback après panne, origine des exports, refus d'accès agent aux fixtures/historiques et révisions concurrentes.

T04–T05 sont livrés sur la branche [codex/body-execution](https://github.com/Hokimisu/Promethee/tree/codex/body-execution). `execution.py`, la migration v3 et les exports distinguent intention, progression et résultat confirmé. Les tests de récupération coupent un sous-processus avant envoi, après envoi, pendant la progression et pendant la transaction finale ; aucune action n'est automatiquement réémise. La documentation donne le chemin de réconciliation. Vérifications : `uv run pytest -q` (répertoire temporaire neuf dédié sous Windows), `ruff check`, `ruff format --check`, `uv build`, Python 3.13.12. Ce travail prépare T07 ; le mouvement réel et son format articulaire dépendent encore de T02–T06.
