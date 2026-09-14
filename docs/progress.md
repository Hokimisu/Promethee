# Avancement vérifié

Ce registre distingue le code livré des intégrations réellement vérifiées. Les critères de référence restent dans le [plan d'implémentation](implementation-plan.md).

| Ticket | État | Preuves |
|---|---|---|
| T00 | Vérifié sur CPU | Python 3.13.12, uv 0.12.5 ; 22 tests initiaux, lint, format et construction réussis ; pause/reprise dans deux processus |
| T01 | Implémenté et vérifié sur CPU | Commandes `catalog` et `act` ; 29 tests passent, dont les tests en sous-processus de `tests/test_cli_actions.py` ; lint, format et construction passent |
| T02 | En préparation | Inventaire matériel effectué ; modèle non installé |
| T03–T13 | À réaliser | Aucune intégration réelle revendiquée |

Les journaux de test et données locales restent dans `.local/` et ne sont pas publiés.

T00–T01 sont livrés sur la branche [codex/manual-world-control](https://github.com/Hokimisu/Promethee/tree/codex/manual-world-control). Le pilotage reste logique et instantané.
