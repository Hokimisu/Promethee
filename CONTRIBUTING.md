# Contribuer

Partir du critère d'acceptation d'un jalon dans la [feuille de route](docs/roadmap.md). Les améliorations du socle doivent rester exécutables sans GPU ni clé API.

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv build
```

Utiliser une branche descriptive, par exemple `codex/world-renderer`. Une contribution explique le problème concret, le comportement résultant, la vérification effectuée et les limites restantes. Mettre à jour les contrats si le comportement public change.

Les noms du code et les commits sont en anglais ; la documentation produit est en français. Aucun secret, donnée personnelle, asset sans provenance ou modèle externe ne doit entrer dans le dépôt. Les enregistrements de tests réels et leurs métriques restent locaux jusqu'à une décision explicite de publication.

Les tests doivent couvrir un risque comportemental réel. Pour un changement de mouvement, joindre une observation visuelle et les conventions du squelette testé. Un rendu de démonstration doit préciser s'il montre une fixture, un modèle préentraîné ou un contrôleur entraîné pour le projet.
