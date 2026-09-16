# Hermes : contexte, personnalité, mémoire et outils

Recherche du 16 septembre 2026. Lecture du code et des sources officielles, sans appel de modèle, sans GPU et sans modification du runtime par cette enquête. La scène vocale de qualification reste séparée des souvenirs personnels.

## Conclusion opérationnelle

Hermes gère déjà la boucle d'outils et l'historique natif de Promethee. Les principales restrictions de l'essai sont intentionnelles : aucune mémoire personnelle, aucun terminal généraliste, aucun deuxième agent décidant du corps. Les retirer ne rendrait pas automatiquement le dialogue plus rapide.

Le défaut concret est le placement du contrat vocal : `dialogue.instructions()` était ajouté entièrement à **chaque message utilisateur**, puis conservé dans l'historique réinjecté. Le raccord natif recommandé est `run_conversation(message_utilisateur, system_message=contrat_stable, conversation_history=historique, task_id=tour)`. Il conserve les instructions approuvées, sans activer SOUL, mémoire ou outils supplémentaires. Mise à jour après l'enquête : ce raccord et le préchauffage jetable sont intégrés, avec [qualification mesurée](11-short-dialogue.md#préchauffage-hermes-qualifié). Le gain est réel lorsque le worker est prêt ; la fluidité continue reste non acquise.

## Versions et périmètre réellement consultés

| Élément | Provenance vérifiée | Conséquence |
|---|---|---|
| Source choisie par la scène | `.local/hermes-agent`, **0.21.3**, commit `2179a279ae04bfadf8efbc49a01ca0abfb738000` ; checkout propre lors de la lecture | Référence principale de ce rapport. |
| Autre installation locale | `C:/Users/Cat6A/AppData/Local/hermes/hermes-agent`, **0.20.5**, commit `cd297653fa4fac85f45f7d3ad8e361db0f14e9be` ; modifications locales présentes | Ne pas confondre l'interpréteur Python utilisé et les modules chargés. |
| Sélection du code | `serve.py` fournit `hermes_root=ROOT / '.local/hermes-agent'` ; `hermes_worker.py` place ce chemin en tête de `sys.path` avant les imports Hermes | Un Python provenant de C n'implique pas que les sources exécutées soient celles de C. |
| Remote des deux checkouts | `https://github.com/NousResearch/hermes-agent.git` | Sources primaires ; pas de conclusion fondée sur un tutoriel tiers. |

Le fichier `agent/prompt_builder.py` modifié dans l'installation C change les instructions de contrôle du navigateur, pas les blocs d'identité examinés. Son SHA-256 observé est `2eeb87b9a3878c7e3f4e7c6458fcba70d74f56d19b526312cf246c0eb4f9c91b`. Aucune modification de cette installation n'a été effectuée. Le préchauffage doit utiliser le **même `hermes_root` que la référence** pour éviter un A/B mêlant changement de version et optimisation.

Révisions primaires : [Hermes 2179a279](https://github.com/NousResearch/hermes-agent/tree/2179a279ae04bfadf8efbc49a01ca0abfb738000), [Hermes cd297653](https://github.com/NousResearch/hermes-agent/tree/cd297653fa4fac85f45f7d3ad8e361db0f14e9be). Les pages officielles consultées ci-dessous sont vivantes ; les lignes de code citées se rapportent à 2179a279 sauf indication contraire.

## Ce que l'intégration désactive — et pourquoi

La construction est explicite dans `src/promethee/hermes_adapter.py`, fonction `create_agent` :

| Réglage actuel | Comportement natif vérifié | Avis pour cet essai |
|---|---|---|
| `skip_context_files=True` | Évite les instructions du dépôt et leur découverte progressive. | À conserver : les plans et fixtures du développeur ne sont pas la vie d'Ariane. |
| `load_soul_identity=False` | Avec le réglage précédent, SOUL n'est pas chargé ; Hermes conserve son identité système par défaut. | Ne pas importer le SOUL personnel. Le contrat Ariane doit devenir une instruction système explicite et stable. |
| `skip_memory=True` | Sans toolset natif `memory`, ni MEMORY.md/USER.md ni fournisseur de mémoire externe ne sont initialisés. | À conserver pendant la qualification. Ce réglage ne supprime **pas** l'historique conversationnel transmis par Promethee. |
| `skip_background_review=True` | Supprime les revues natives de mémoire/skills en fin de tour. | À conserver : elles ne répondent pas au besoin vocal immédiat et ne doivent pas apprendre les essais. |
| `max_iterations=8` | Borne la boucle de décisions/appels API, pas la durée d'une inférence ni le nombre de tokens pensés. Une sortie de grâce sans outils existe à l'épuisement du budget. | Ne pas l'abaisser arbitrairement : un dialogue simple n'utilise normalement qu'un appel ; des actions peuvent nécessiter plusieurs résultats. |
| Cinq outils MCP autorisés, découverte exacte vérifiée | Lecture du monde/capacités/exécution, soumission et annulation ; pas de terminal, skills ou délégation. | Périmètre approprié. Les quatre outils mémoire Promethee n'existent qu'avec un coffre explicitement raccordé ; la scène utilise `vault=None`. |
| `tool_search` désactivé | Pas de sélection différée parmi une grande bibliothèque d'outils. | Justifié pour cinq outils déjà petits et connus. |

Sources : [initialisation mémoire](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/agent_init.py#L1228), [identité et contexte](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/system_prompt.py#L488), [revue de fin de tour](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/turn_finalizer.py#L609), [budget](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/turn_iteration_prep.py#L349). La documentation distingue aussi [mémoire durable](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory), [contexte du projet](https://hermes-agent.nousresearch.com/docs/user-guide/features/context-files) et [identité SOUL](https://hermes-agent.nousresearch.com/docs/user-guide/features/personality).

## Contrat vocal répété et emplacement natif

Mesure CPU sur le texte approuvé présent au moment de l'enquête : **2 852 caractères** par `instructions()`, soit 1 305 de personnage et 1 547 de contrat vocal. Empreinte de `dialogue.py` : `109541ad578fb309eefb1f145c394f8a541c7d62b7f23b55bc43c1d256af905b`. Les changements ultérieurs doivent recalculer ces nombres.

Avec un appel API par tour et sans compression, le dixième appel contient 28 520 caractères de répétitions de ce contrat dans l'historique ; un contrat système unique contient 2 852 caractères. Sur dix appels, le seul volume cumulé de ce texte passe mathématiquement de **156 860 à 28 520 caractères**. Ces chiffres excluent réponses, résultats d'outils et instructions natives : **ce ne sont ni des tokens facturés, ni une économie monétaire mesurée**. Les tours avec plusieurs appels d'outils amplifient la retransmission.

Le JSON final `{text, delivery}` a une utilité différente : il associe la réplique à son intention vocale. `DirectedWorker` conserve les `messages` Hermes et enregistre séparément le texte parlé. Il ne faut pas réécrire les anciens appels/résultats d'outils pour « nettoyer » arbitrairement l'historique, ni assimiler texte généré et parole effectivement lue.

Raccord natif précis, sans changer les mots approuvés :

```python
agent.run_conversation(
    message_utilisateur,
    system_message=contrat_stable,
    conversation_history=historique_natif,
    task_id=turn_id,
)
```

La [signature](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/conversation_loop.py#L1573) accepte ce paramètre. Le [constructeur du prompt](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/system_prompt.py#L640) le place dans la section système `context`, avant la partie volatile. L'[assemblage API](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/turn_context.py#L1134) le transmet hors des messages utilisateur persistés. Le système natif par défaut n'est pas remplacé intégralement : il reste suivi de notre contrat.

**Piège de configuration :** renseigner seulement `agent.system_prompt` dans YAML ne suffit pas à notre constructeur direct `AIAgent`. C'est la CLI qui résout ce champ et transmet `ephemeral_system_prompt` (`cli.py:2779`, `hermes_cli/cli_agent_setup_mixin.py:546`). Le chemin Promethee saute cette CLI. Le paramètre explicite `system_message` est donc le raccord approprié ; `platform` et les `platform_hints` servent aux consignes d'une surface, pas à stocker un historique. Pas besoin d'activer SOUL.

Lors du passage, ne pas modifier rétrospectivement les historiques existants : lancer une session de qualification neuve pour l'A/B. La validation de `ConversationStore.finish` exige que le message utilisateur réellement soumis soit conservé par l'historique natif ; un changement de `persist_user_message` implicite casserait ce contrat.

## Cache : bénéfice certain et limite réelle

Hermes met son prompt système en cache dans l'instance et peut le restaurer depuis sa base de session. Nos profils jetables reconstruisent une instance et un environnement par tour : le même `session_id` Promethee ne suffit pas à retrouver la base d'un autre profil. [Restauration native](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/conversation_loop.py#L651).

Deux détails évitent un mauvais diagnostic :

- `_timestamp_line` ne contient pas l'heure à la seconde : la **date est stable dans la journée**. `pass_session_id` est faux par défaut. Le modèle/fournisseur changent seulement si notre configuration change. [Source](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/system_prompt.py#L433).
- `_active_profile_line` inclut le nom et le chemin du profil `promethee-turn-…`. Ils changent réellement à chaque tour et figurent dans le préfixe natif. Le transport Codex calcule sa clé avec le **texte complet des instructions**, les outils et le périmètre de session. [Profil](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/system_prompt.py#L344), [calcul de clé](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/transports/codex.py#L304), [utilisation](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/transports/codex.py#L602).

Une vérification CPU de la fonction de hash extraite du code confirme : entrées identiques → même clé ; seul nom de profil différent → autre clé. Aucun constructeur d'agent et aucun appel API n'ont été exécutés. Cette clé est un **indice de routage**, pas la preuve d'un cache touché ou manqué côté fournisseur. Le passage à `system_message` supprime la croissance répétitive, mais ne garantit pas à lui seul un cache fournisseur chaud.

Ne pas falsifier le profil annoncé, réutiliser un transport MCP lié à un autre tour ou altérer la mémoire pour stabiliser ce hash. Instrumenter d'abord empreintes/taille des parties du prompt et compteurs de tokens mis en cache lorsqu'ils sont réellement fournis. La [documentation de compression/cache](https://hermes-agent.nousresearch.com/docs/developer-guide/context-compression-and-caching) décrit le mécanisme ; ses optimisations Anthropic ne se transfèrent pas automatiquement au transport Codex.

## Outils et parallélisme : ne pas confondre trois mécanismes

1. **Plusieurs outils dans une réponse LLM** réduisent les allers-retours si les lectures sont indépendantes. Le transport Codex autorise déjà `parallel_tool_calls=True` lorsque des outils sont fournis.
2. **Exécution simultanée locale des outils MCP** nécessite `supports_parallel_tool_calls: true` au niveau du serveur. Notre profil ne le définit pas ; le défaut natif est faux. Ce réglage concerne tout le serveur, pas seulement les annotations read-only. Ne pas l'activer globalement sur un serveur mêlant lecture, soumission et annulation. Les dépendances `read_world → submit_action` resteraient séquentielles et le conflit de révision ne serait pas résolu.
3. **Parole, corps et décision suivante** sont orchestrés par les boucles Promethee. Le thread corps et le worker vocal ne doivent pas attendre qu'Hermes effectue un polling de fin de mouvement. Ajouter une délégation ou MoA natifs créerait du calcul et un autre décideur sans corriger ce contrat ; aucune extension d'outils n'est recommandée.

Sources : [admission et barrières du scheduler](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/tool_dispatch_helpers.py#L148), [opt-in MCP](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/tools/mcp_tool_discovery.py#L526), [documentation MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp#parallel-tool-calls), [boucle native](https://hermes-agent.nousresearch.com/docs/developer-guide/agent-loop).

Les observations de présence modifient toujours la révision entre lecture et soumission. Les cinq outils actuels passent directement par leur `ExecutionService`, sans rendez-vous avec `BodyAdapter`. Ce problème d'action explicite **reste distinct et non résolu par ce rapport**, par le JSON vocal ou par le préchauffage.

## Cinq actions pragmatiques, sans nouvelle bibliothèque d'outils

| Priorité | Action | Statut et validation attendue |
|---|---|---|
| 1 | Déplacer les instructions approuvées vers `system_message`, avec un message utilisateur contenant uniquement l'intervention/contexte utile. | Intégré. Six tours réels : aucune copie du contrat dans les messages utilisateur persistés, JSON vocal validé. Historique natif conservé. |
| 2 | Préchauffer un seul worker jetable sur un futur identifiant privé, puis activer **ce même tour** avec historique frais ; vérifier les empreintes de prompt/cache en parallèle. | Préchauffage intégré et mesuré sur la même source G ; instrumentation du cache fournisseur encore à faire. Aucun `run_conversation` ni mutation autorisée avant activation. `host.cancel()` invalide le tour actif et conserve le worker réservé inactif ; le serveur vivant l'utilise pour les interruptions start/say/stop. `host.close()` détruit actif et réserve à la fermeture du service ; la réserve a aussi une expiration bornée. |
| 3 | Tester `agent.environment_probe: false` dans le profil dédié. | Recommandé, non appliqué par ce rapport. Hermes lance autrement des sondes d'environnement en arrière-plan (`agent_init.py:1336–1340`) sans utilité pour nos cinq outils. Le commentaire upstream estime environ 0,5 s de sous-processus ; ce n'est **pas** une économie de 0,5 s démontrée sur notre chemin critique. Mesurer construction et délai avant appel. |
| 4 | Tester `agent.task_completion_guidance: false` uniquement dans le profil vocal, en conservant intégralement les règles explicites « accepté ≠ terminé » et monde autoritaire. | Recommandé pour A/B, non appliqué. Le bloc générique demande de finir/vérifier le travail avant de répondre ; il peut concurrencer notre objectif parler pendant l'action. C'est une hypothèse de comportement, pas la cause prouvée des lectures en boucle. Vérifier action acceptée puis parole sans polling répété, refus explicite et interruption correcte. |
| 5 | Rendre les réponses des **outils existants** plus compactes pour le dialogue, sans modifier leurs reçus persistés. | Recommandé, non appliqué. Garder identité d'action, statut, erreur, source, fraîcheur et position/posture effectives ; éviter de réinjecter chaque matrice/quaternion VRM pour un simple statut. Préserver révision et provenance, ne pas résumer un échec en succès. Mesurer caractères/tokens avant et après, puis vérifier reprise après interruption. |

Les réglages 3 et 4 sont réellement lus par le constructeur natif dans [`_apply_agent_section`](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/agent/agent_init.py#L1299) ; ils ne nécessitent pas de reconstruire un framework d'outils. Le réglage `max_iterations=8` reste inchangé dans ces propositions.

La mémoire durable et la recherche de souvenirs sont utiles pour une future session personnelle autorisée, mais elles ne remplacent ni le contexte conversationnel courant ni le résultat observé du corps. Aucun souvenir de test, SOUL personnel ou fournisseur de mémoire n'a été chargé ou ajouté pendant cette enquête.
