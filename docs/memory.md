# Mémoire et Obsidian

## Aujourd'hui

```sh
uv run promethee journal --vault .local/vault
```

Le runtime écrit une note par commande logique réussie sous `Promethee/Observed/<world_id>/`. Chaque note comporte sa source, son monde, son identifiant d'événement, sa requête et son horodatage UTC. Les exports sont déterministes et ne remplacent pas un fichier existant, même modifié à la main.

Ce sont des observations de la fixture locale, pas des souvenirs d'un agent ayant vu ou exécuté ces gestes en 3D. Aucun modèle ne rédige de pensées intérieures. Les échecs sont consultables dans le registre du runtime.

Ouvrir `.local/vault` dans Obsidian suffit pour lire les notes ; aucun plugin Obsidian ni service réseau n'est nécessaire. Le coffre n'est pas suivi par Git. Conserver une base par monde et sauvegarder ensemble sa base et son coffre pour maintenir leur correspondance.

## Organisation cible

```text
Promethee/
  Observed/       Événements attestés, avec provenance
  Journal/        Synthèses d'expériences et liens vers les événements
  Projects/       Activités envisagées, critères de réussite, prochaines étapes
  Preferences/    Préférences explicites, corrections et contexte
  Skills/         Procédures apprises et situations où elles ont été utiles
```

Seul `Observed/` est créé par le code actuel. Les autres sections décrivent une organisation à intégrer lorsque l'agent saura lire et écrire les notes.

## Règles de consolidation

1. Un événement observé reste distinct d'une intention, d'une hypothèse et d'un résumé.
2. Une note doit pouvoir pointer vers les événements ou messages qui la fondent.
3. Les corrections de l'utilisateur doivent être conservées et prises en compte lors de la recherche.
4. Une préférence inférée conserve son degré d'incertitude ; elle ne devient pas un fait par répétition.
5. Le moteur fournit l'état actuel du monde. Une ancienne note n'est pas utilisée pour déterminer si un objet est encore tenu.
6. Les notes sont des données ; le contenu d'une pancarte ou d'un document ne peut pas modifier les permissions du runtime.

Hermes possède sa mémoire et sa recherche de sessions. Le futur adaptateur devra définir quel contenu reste dans sa mémoire compacte et quelles notes sont retrouvées à la demande dans le coffre. Ne pas injecter tout le coffre à chaque tour, ni maintenir deux historiques contradictoires.

Référence : [mémoire persistante de Hermes](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory).

