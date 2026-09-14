# Promethee

[![CI](https://github.com/Hokimisu/Promethee/actions/workflows/ci.yml/badge.svg)](https://github.com/Hokimisu/Promethee/actions/workflows/ci.yml)

Un avatar IA doté d'un corps, d'une mémoire et de capacités d'action dans un espace virtuel persistant.

Le projet fournit un espace que l'avatar peut percevoir et modifier, des objets utilisables et une mémoire consultable dans Obsidian. Un agent peut former et réviser ses intentions ; le monde lui renvoie ce qui s'est effectivement passé. Aucun scénario de vie, routine ou préférence d'objet n'est prescrit.

**État actuel : socle local exécutable.** La démonstration est un scénario déterministe dans un monde logique. L'avatar 3D, les modèles IA, la voix, Hermes et la génération de mouvements ne sont pas encore intégrés. Aucun appel réseau, aucune clé API et aucun GPU ne sont nécessaires pour lancer ce socle.

## Essayer

Prérequis : Python 3.12+ et [uv](https://docs.astral.sh/uv/getting-started/installation/).

```sh
git clone https://github.com/Hokimisu/Promethee.git
cd Promethee
uv sync --locked
uv run promethee demo --pause-after 4
uv run promethee world
uv run promethee demo --resume
uv run promethee journal
```

La première commande de démonstration crée trois objets, écrit une pancarte et suspend l'activité. La reprise charge le plan sauvegardé, prend le doudou, rejoint la chaise et s'assied. Relancer la démonstration terminée ne recrée pas les objets.

Cette séquence est une fixture de vérification de la persistance. Elle ne définit pas les comportements attendus du futur avatar. Ses actions et ses exports restent des données de test, à exclure des prompts, de la mémoire initiale et des objectifs d'entraînement de l'agent.

- `world` affiche l'état persistant, stocké dans `.local/promethee/world.sqlite3`.
- `journal` exporte les actions logiques réussies dans `.local/vault/Promethee/Observed/`. Ouvrir `.local/vault` comme coffre Obsidian pour les consulter.
- Les exports ne réécrivent pas les notes existantes. Les essais rejetés restent dans le registre SQLite et ne deviennent pas des souvenirs de réussite.
- Pour un essai indépendant, choisir un autre dossier : `uv run promethee --data-dir .local/second-demo demo`.

Toutes les commandes fonctionnent sous PowerShell et dans un terminal Linux. Les données personnelles et les exports locaux sont ignorés par Git.

Pour piloter librement ce monde logique, consulter `uv run promethee catalog`, puis écrire une action `{ "kind": "move", "args": { "position": [2, -3] } }` dans un fichier UTF-8 `action.json` :

```sh
uv run promethee --data-dir .local/manual act --request-id mouvement-1 --file action.json
uv run promethee --data-dir .local/manual world
```

Cette commande réalise une transition instantanée, sans activité préécrite ni mouvement 3D. Voir les [contrats et codes de sortie](docs/contracts.md).

## Ce qui est livré

| Élément | État |
|---|---|
| État du monde et registre d'actions SQLite | Exécutable |
| Actions validées et identifiants de requête idempotents | Exécutable |
| Plan sauvegardé, pause, reprise après redémarrage | Exécutable |
| Catalogue logique chaise / pancarte / doudou / lit / TV | Exécutable ; les usages lit/TV sont à implémenter |
| Journal Markdown lisible dans Obsidian | Export exécutable ; recherche mémoire à connecter |
| Contrôles automatiques et tests de comportement | Fournis |
| Astra dans Hermes, voix GPT-Live | Architecture proposée ; adaptateurs à développer |
| ARDY, modèle 3D, contacts, rendu | Intégration à évaluer et développer |
| Initiative autonome et services externes | Jalons ultérieurs |

## Architecture cible

```mermaid
flowchart LR
    User[Utilisateur] <-->|Conversation| Voice[Voix]
    Voice <--> Agent[Astra dans Hermes]
    Agent <--> Memory[Mémoire et notes Obsidian]
    Agent -->|Actions validées| World[Monde persistant]
    Agent -->|Intention et cibles| Body[Contrôle du corps]
    Body --> World
    World -->|Événements observés| Agent
```

Le moteur du monde décide si une action a réussi. Un prompt décrit une intention ; les positions, les objets et les contraintes rendent cette intention exécutable. La voix et le corps partagent le même contexte, avec ou sans activité en cours. Voir [l'architecture](docs/architecture.md) et les [contrats actuels](docs/contracts.md).

## Développer

Commencer par le [plan d'implémentation](docs/implementation-plan.md) : T00 vérifie le socle, puis T01 ajoute un pilotage manuel sans scénario. Chaque ticket indique son périmètre, ses dépendances et ses critères de validation.

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv build
```

Les tests couvrent la reprise dans un nouveau processus, les commandes concurrentes, le rejet des actions impossibles, les transactions interrompues et la préservation des notes modifiées.

```text
src/promethee/    Monde logique, persistance, scénario et export
tests/           Vérifications de comportement
docs/            Vision, architecture, contrats et jalons
.github/         CI et modèles de contributions
```

## Documents

- [Vision et expérience souhaitée](docs/vision.md)
- [Architecture et décisions initiales](docs/architecture.md)
- [Contrats du socle exécutable](docs/contracts.md)
- [Intégrations et références officielles](docs/integrations.md)
- [Mémoire et organisation Obsidian](docs/memory.md)
- [Feuille de route et critères d'acceptation](docs/roadmap.md)
- [Plan d'implémentation pour le développeur](docs/implementation-plan.md)
- [Contribuer](CONTRIBUTING.md)
- [Instructions pour les agents de développement](AGENTS.md)

Le code original du dépôt est sous [licence MIT](LICENSE). Les modèles, captures de mouvement, voix et assets externes conservent leurs propres licences ; aucun n'est redistribué ici. Promethee est un projet indépendant, sans affiliation avec OpenAI, NVIDIA ou Nous Research.
