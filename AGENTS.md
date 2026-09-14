# Promethee — instructions de développement

Lire `README.md`, `docs/architecture.md` et le jalon concerné dans `docs/roadmap.md` avant de modifier le projet.

## Portée

Promethee est un projet autonome. Ne pas importer les contraintes du robot Microduck, son contrat d'observation ou ses actionneurs. Le socle actuel est un monde logique Python sans modèle IA, physique ni rendu.

Préserver la distinction entre capacité livrée, fixture déterministe, intégration proposée et résultat effectivement vérifié. Ne pas présenter la mémoire comme un entraînement des poids, ni revendiquer une conscience.

## Commandes

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv build
```

## Invariants

- Le monde et le résultat d'exécution font autorité ; un prompt ou une parole n'atteste pas une action.
- Une commande rejouée avec le même ID n'a aucun nouvel effet. Un ID avec un contenu différent est refusé.
- Le monde, l'événement et le curseur d'activité sont persistés atomiquement.
- La pause survit au redémarrage ; une activité échouée n'est jamais marquée terminée.
- Les notes exportées ont une provenance et préservent les modifications manuelles.
- La voix, le corps et l'agent partageront un contexte d'activité cohérent.
- Ne jamais stocker de token, conversation personnelle, coffre réel ou poids de modèle dans Git.
- Garder les dépendances des modèles optionnelles lors de leur introduction ; le socle reste testable sur CPU.

## Modifications

Écrire le plus petit changement qui satisfait un critère du jalon. Pas de framework de plugins, microservices ou abstraction de fournisseur avant un besoin concret. Vérifier les interfaces officielles avant d'intégrer un modèle ; fixer les versions testées et documenter les licences des assets.

Pour les changements d'état, couvrir les préconditions, échecs, retransmissions et reprises. Pour le mouvement, regarder les vidéos et inspecter les contacts ; ne pas se contenter des métriques numériques. Pour un contrôleur asynchrone, remplacer explicitement la sémantique de succès instantané du prototype.

## Rédaction d'interface

Un seul titre visible par bloc. Ajouter un texte secondaire uniquement s'il apporte une condition, une conséquence, une contrainte ou une action. Supprimer slogans, transitions décoratives et répétitions. Si retirer un texte ne change ni la compréhension ni l'action, l'omettre.
