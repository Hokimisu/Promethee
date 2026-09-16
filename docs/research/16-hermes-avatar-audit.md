# Hermes : capacités natives et besoins d’Ariane

Audit du 16 septembre 2026 demandé par l’utilisateur, mené avec trois agents
en parallèle : capacités natives, intégration Promethee et dialogue en temps
réel. Lecture du code réellement chargé et de la documentation officielle.
Ce rapport ne change ni la scène en cours, ni la voix, ni les modèles.

## Conclusion

Dans la configuration auditée, Promethee utilise bien la boucle d’agent Hermes. La scène vocale
n’utilise pas encore son ensemble de fonctions de mémoire, de compétences et
de consolidation. Elle reste configurée comme un essai temporaire. Cette
distinction explique une partie de l’écart entre les possibilités d’Hermes
et celles actuellement accessibles à Ariane ; elle n’explique pas à elle
seule les délais ou les défauts de mouvement.

Après cet audit, l’utilisateur a demandé un essai avec un harnais sans Hermes.
Une boucle Responses directe optionnelle a été ajoutée et la scène a été
lancée avec elle ; voir [l’essai du harnais direct](17-custom-harness.md).
La comparaison reste à qualifier : ce démarrage ne démontre ni un gain de
latence ni une meilleure continuité. Le choix entre les deux voies reste
ouvert. Dans les deux cas, le runtime Promethee demeure responsable des faits
du monde : une compétence mémorisée ne prouve pas qu’un geste a été exécuté,
et un souvenir ne remplace pas l’observation courante.

## Sources et portée

- Promethee examiné : `c47f65607c559259d191c17590bff72107d30f1b`.
- Hermes réellement importé : `.local/hermes-agent`, version **0.21.3**,
  commit [`2179a279ae04bfadf8efbc49a01ca0abfb738000`](https://github.com/NousResearch/hermes-agent/tree/2179a279ae04bfadf8efbc49a01ca0abfb738000).
  Le checkout était propre pendant cet audit.
- La [dernière release publiée consultée](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.9.14)
  annonce aussi 0.21.3. La branche `main`, observée à
  `2cfb655d52e7e482523236c4012b61fcb54b37ce`, a continué d’évoluer.
  Un même numéro de version ne garantit pas des sources identiques.
- Les rapports [12](12-hermes-lifecycle.md), [13](13-hermes-context-tools.md),
  [14](14-hermes-tool-latency.md) et [15](15-hermes-persistent-tools.md)
  contiennent les qualifications antérieures. Leurs mesures sont reprises
  comme preuves historiques, sans les présenter comme de nouveaux essais.

Les modules importés proviennent du checkout G, même si l’interpréteur se
trouve dans l’installation Hermes sur C. Aucune mise à jour, installation,
inférence ou génération vocale n’a été lancée pour cette recherche.

## Ce qui fonctionne déjà dans le bon composant

Dans le chemin Hermes, la boucle native `AIAgent.run_conversation` choisit les
outils, traite leurs résultats et produit la réponse. L’hôte lui délègue cette
boucle ; l’expérience directe ultérieure possède sa propre boucle séparée.
Le contexte conversationnel est persisté par l’hôte et réinjecté ; le résident
conserve agent et connexion MCP entre les tours réussis. La destruction sur
interruption protège contre les propositions devenues obsolètes.

Le raccord récent a supprimé une reconnexion inutile : sur la paire publiée,
l’actualisation MCP du second tour passe de **1,695 s à 0,012 s**. Le résultat
complet prend encore **7,909 s**, avec deux appels modèle. C’est un essai CPU
de transport, sans synthèse vocale, pas une mesure du délai avant le premier
son. Voir [le protocole et ses limites](15-hermes-persistent-tools.md).

Les règles du corps restent justifiées dans Promethee : soumission idempotente,
révision du monde, contrôleur unique, interruption et distinction entre
acceptation et résultat. Hermes est un moteur d’agent généraliste ; sa
[boucle native](https://hermes-agent.nousresearch.com/docs/developer-guide/architecture/)
ne fournit pas à elle seule les preuves d’exécution d’un avatar.

## Trois formes de continuité à distinguer

| Besoin | Mécanisme disponible | Situation auditée dans le chemin Hermes |
| --- | --- | --- |
| Se rappeler la conversation en cours | Historique natif et compaction Hermes ; persistance de l’hôte | Historique raccordé ; longues sessions à qualifier |
| Retrouver des faits, préférences incertaines et corrections | Mémoire sourcée Promethee / Obsidian, accessible à Hermes | Outils livrés dans le pont textuel ; coffre absent de la scène vocale |
| Retenir une manière utile de faire quelque chose | Compétences natives Hermes ; provenance à conserver dans leur intégration | Non exposées à Ariane |

Le constructeur passe explicitement `skip_memory=True` et
`skip_background_review=True`, avec les seuls outils MCP Promethee. Les
compétences natives ne sont pas exposées. Ajouter `--vault` au pont textuel
active les quatre outils de mémoire sourcée Promethee, pas les magasins natifs
`MEMORY.md` et `USER.md`. La scène auditée passe `vault=None`.

L’hôte borne aussi l’historique sérialisé à **512 Kio** dans
`conversation.py:bounded_history`. Une nouvelle entrée peut être refusée avant
son envoi à Hermes, donc avant une éventuelle compaction par celui-ci ; les
résultats retournés sont également bornés. Aucune troncature silencieuse n’est
effectuée. La présence du compresseur natif ne garantit donc pas, à elle seule,
une conversation longue sans interruption.

Les [compétences Hermes](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/)
stockent des procédures consultables et modifiables. Leur création n’entraîne
pas les poids du modèle. Pour Ariane, elles doivent conserver des méthodes
issues d’expériences réelles, sans transformer un scénario d’essai en routine
ou en préférence.

Notre mémoire sourcée répond au [contrat T10](../implementation-plan.md#t10--rendre-la-mémoire-utilisable) :
corrections, origine des faits et séparation des mondes. La remplacer par une
deuxième copie libre des mêmes souvenirs ferait perdre ces garanties.

Pour raccorder le rappel et la synchronisation de mémoire, Hermes propose un
[`MemoryProvider`](https://hermes-agent.nousresearch.com/docs/developer-guide/memory-provider-plugin/)
avec notamment `prefetch` et `sync_turn`. Ce serait un adaptateur vers le
stockage existant, à qualifier ; ce raccord n’est pas livré et ne constitue
pas, à lui seul, une consolidation. Hermes dispose séparément d’une revue
native de mémoire et de compétences après certains tours, désactivée ici.

La synchronisation doit respecter la portée du profil et éviter de retarder
la parole. `sync_turn` peut être lancé avant que l’hôte ait validé le résultat
dans `ConversationStore.finish` : son appel ne vaut donc pas admission durable
du tour. Une écriture factuelle doit conserver cette validation et ses sources.
Le reçu de lecture audio est encore distinct : une réponse générée n’atteste
pas que toute la phrase a été lue ou entendue.

Un [moteur de contexte personnalisé](https://hermes-agent.nousresearch.com/docs/developer-guide/context-engine-plugin/)
sert à changer la sélection ou la compaction du contexte. Il n’est pas requis
pour simplement enregistrer des souvenirs. Dans la voie Hermes, aucun besoin
de remplacer ce composant n’a été établi par cet audit.

## Identité et périmètre de la scène

Le constructeur Hermes audité désactive `load_soul_identity` et la découverte des
fichiers de contexte. Dans cette configuration, Hermes conserve son identité
native par défaut ; le personnage Ariane est ajouté par notre instruction
système. C’est un chevauchement réel de consignes, mais sa responsabilité dans
les changements de personnalité n’a pas été mesurée.

Le profil est créé à neuf pour chaque cycle de worker ; le résident conserve
le sien durant sa vie. Ce n’est pas encore un stockage cognitif durable entre
toutes les reprises. L’historique du monde persiste indépendamment, et le
partage de l’authentification ne partage pas la mémoire.

Si la voie Hermes est retenue pour cette identité, un
[`SOUL.md` dédié](https://hermes-agent.nousresearch.com/docs/user-guide/features/personality/)
au profil d’Ariane permet de remplacer l’identité par défaut tout en
gardant les instructions du dépôt hors de sa vie. La direction de jeu de
chaque réplique reste séparée de cette identité durable. L’adoption doit
reprendre le personnage approuvé, sans importer le profil personnel de
l’utilisateur ni inventer de passé commun.

La scène auditée impose aussi dans son propre contrat des déplacements inférieurs à
un mètre, deux postures et l’absence de manipulation du décor. Ces restrictions
de l’essai ne sont pas des limites intrinsèques d’Hermes. Les élargir exige
d’exposer des capacités effectivement raccordées au corps et au monde.

## Recherche parallèle

Les notes détaillées de travail sont conservées localement :

- `.local/hermes-research-native-capabilities.md` ;
- `.local/hermes-research-integration-audit.md` ;
- `.local/hermes-research-realtime.md`.

Elles complètent les sources épinglées et les qualifications liées ci-dessus.
Les pistes recommandées restent distinctes des capacités effectivement livrées.
