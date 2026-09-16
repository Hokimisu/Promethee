# Hermes conservé : réduire les lectures avant une action

## Modification

Le [harness direct](17-custom-harness.md) n'a pas réduit systématiquement
la latence. Hermes reste le moteur retenu. Cette qualification porte sur un
autre levier : fournir l'observation au premier appel du modèle, au lieu de
lui faire décider plusieurs lectures avant de pouvoir agir.

L'option `world_context: true` de la scène, ou `--world-context` de l'hôte
texte, installe un petit plugin dans le profil Hermes isolé. Le hook natif
`pre_llm_call` appelle une fois `read_world(detail="summary",
include_capabilities=True)` au début du tour. Le monde, les révisions, les
reçus et les capacités proviennent de la même transaction, après expiration
des contrôleurs absents. L'option reste désactivée par défaut.

Le plugin utilise `ctx.dispatch_tool`, avec le scope natif du profil et le
`task_id` immuable du tour. Il n'appelle aucun modèle et n'exécute aucune
commande corporelle. Les outils, la boucle de décision, l'authentification,
la persistance et la gestion des interruptions restent ceux de Hermes.
Les préconditions d'une commande sont toujours revérifiées au moment de
son admission ; une lecture préalable ne garantit pas un succès futur.

## Conservation du contexte

Hermes conserve le texte utilisateur original dans `content` et l'observation
datée dans son champ natif `api_content`. Les observations précédentes deviennent
historiques. Aucun résultat d'outil fictif n'est ajouté à la conversation et
le préfixe système ne change pas. Le plugin n'a aucun cache partagé.

Un autre monde, un autre tour, une autorisation expirée, un résultat invalide
ou un contexte complet de plus de 10 000 caractères sont omis. Les outils
restent alors accessibles pour une lecture explicite. La limite inclut le
préambule : au-delà, Hermes épinglé remplacerait le contexte par un extrait
et un fichier que cet agent restreint ne peut pas lire. Le plugin ne coupe
jamais les données pour respecter cette limite.

Le hook est appelé une fois au début du tour, pas avant chaque aller-retour
au modèle. Un résultat ultérieur prévaut ; en cas de révision refusée, l'agent
doit relire le monde. Le délai natif du hook n'annule pas un appel MCP déjà
parti ; une défaillance peut donc encore coûter le délai de transport avant
le retour aux outils ordinaires. Cet essai ne qualifie pas les longues
conversations ni leur compaction.

## Comparaison réelle du 16 septembre 2026

Deux paires de quatre tours, mêmes sources gelées, mêmes outils et identité,
Luna low, Hermes résident préchauffé, mondes neufs et contrôleur CPU statique.
Aucune voix ni animation n'est produite dans ce protocole : une demande de
geste reste acceptée sans exécution. Les tests CPU sont terminés avant les
mesures. L'ordre est déclaré avant chaque paire : sans/avec, puis avec/sans.
Toutes les sorties sont conservées, sans sélection d'une meilleure réponse.

Durée jusqu'à la réponse textuelle complète, en secondes :

| Demande | Sans, série 1 | Avec, série 1 | Sans, série 2 | Avec, série 2 |
| --- | ---: | ---: | ---: | ---: |
| Salutation ouverte | 6,13 | 5,34 | 7,17 | 4,93 |
| Réaction à une plaisanterie | 3,58 | 2,16 | 3,72 | 2,24 |
| Lever les bras et répondre | 8,51 | 6,16 | 11,05 | 5,15 |
| Vérifier ce qui a vraiment été exécuté | 5,10 | 6,03 | 6,87 | 4,87 |

La demande de geste utilise deux tours d'outils décidés par le modèle sans
l'option (`read_world`, puis `submit_action`), contre un seul avec
(`submit_action`). Le hook fait lui-même une lecture locale dans ce dernier
cas. La vérification conserve son appel `read_execution` dans les quatre
séquences ; les conversations simples n'utilisent aucun outil décidé par le
modèle. Ces tours d'outils ne constituent pas un décompte des éventuelles
tentatives réseau internes du fournisseur.

Les huit tours avec option contiennent une observation du bon monde et du bon
tour dans le sidecar natif. Les seize messages utilisateur restent intacts.
Les préparations de 8,13 à 8,45 s sont exclues des durées ci-dessus. Les données
locales sont sous `.local/hermes-world-context-ab-0{1,2}-{baseline,prefetch}` :
manifestes avec empreintes des sources, SQLite natif, résultats et analyses.

Le gain établi dans ces essais est la suppression d'un tour de lecture avant
le geste. Les autres écarts de durée ne suffisent pas à attribuer un gain
général au plugin : petit échantillon, service distant, réponses et historique
qui divergent. La voix, le temps d'exécution ARDY et le délai réseau utilisateur
ne sont pas compris dans cette comparaison.

**Limite de qualité observée :** au troisième tour, trois réponses sur quatre
disent « bras levés » alors que ce contrôleur ne fait qu'accepter la commande.
La quatrième dit « je lève les bras », également sans observation motrice.
Les quatre rectifient au tour suivant en citant l'absence d'exécution confirmée.
Le stockage n'invente aucun succès, mais la formulation du modèle peut toujours
anticiper le geste. Cette optimisation ne résout pas cette limite.

## Vérification dans la scène

Hermes est rétabli sur `http://127.0.0.1:2392`, avec `world_context: true`,
le monde précédent et la même référence VoxCPM2. Deux tours contrôlés relient
le modèle, la synthèse, le navigateur et le contrôleur ARDY :

| Mesure | Réplique simple | Réplique avec bras levés |
| --- | ---: | ---: |
| Réponse du cerveau | 4,45 s | 5,63 s |
| Premier PCM après départ de la synthèse | 0,123 s | 0,104 s |
| Création du tour → acquittement de début de lecture navigateur | 5,05 s | 6,13 s |
| Audio lu | 6,56 s | 4,32 s |
| Sous-alimentations audio détectées | 0 | 0 |

Les deux contextes natifs sont présents et les messages originaux préservés.
La demande de bras appelle uniquement `submit_action`, puis le reçu devient
`completed`, source `kinematic`. La posture bras levés est visible. Deux relevés
de 130 échantillons observent les lèvres pendant le son, puis leur retour à
zéro. Le microphone reste coupé. Cela vérifie la lecture numérique et le rendu,
pas l'écoute acoustique de l'utilisateur ni la naturalité de tous les mouvements.

Traces locales : `.local/realtime-microphone-runs/session-3ffedb128d25`,
avec `qualification-context.json`, `metrics.json` et `playback.jsonl`.
La configuration active est `.local/realtime-microphone-context.json`.
Le monde repris reste celui de `session-77a482df60eb` ; aucun historique n'est
remplacé. Les interventions ultérieures de l'utilisateur sont hors comparaison.

L'attente avant le son est encore de plusieurs secondes. Dans ces deux tours,
le délai principal précède la synthèse ; optimiser le temps jusqu'au premier
PCM seul ne supprimera pas cette attente. Une livraison progressive de la
réponse, avant sa génération complète, reste une piste à qualifier sans perdre
la cohérence de la direction vocale et des résultats d'action.

## Validation logicielle

Suite socle et scène : 1 234 tests réussis, 2 ignorés et 7 sous-tests réussis.
Ce total local inclut 24 tests d'un chantier de qualification motrice indépendant,
dont les fichiers ne sont pas publiés avec ce changement.
Les 58 tests du plugin sont rejoués après l'ajout du cas limite de longueur
finale. Ruff, format et construction du paquet réussissent. Les tests couvrent
l'expiration du contrôleur, la lecture atomique, le transport MCP réel,
l'autorité du tour, les valeurs booléennes strictes, les contextes invalides
et l'installation optionnelle dans un profil neuf. Aucun modèle ni poids
n'est ajouté au socle.

## Références vérifiées

- Hermes `2179a279ae04bfadf8efbc49a01ca0abfb738000` (0.21.3), sources locales :
  `agent/turn_context.py`, `hermes_cli/plugins.py`,
  `hermes_cli/plugins_dispatch.py`, `tools/hook_output_spill.py`.
- [Hook natif pre_llm_call](https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks/#pre_llm_call).
- [Contexte et préfixes stables](https://hermes-agent.nousresearch.com/docs/developer-guide/context-engine-plugin/).

La mémoire Obsidian, les compétences et la consolidation ne sont pas changées.
La voix VoxCPM2, sa référence approuvée, le modèle Luna low et les réglages ARDY
restent identiques. Aucun coût de fournisseur n'est déduit de ces mesures.
