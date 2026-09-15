# Plan d'implémentation

Ce document s'adresse à la personne qui va coder la suite de Promethee. Il transforme les [jalons produit](roadmap.md) en tâches vérifiables. L'ordre concerne la construction du logiciel ; il ne décrit aucune vie à faire jouer à l'avatar.

État de départ relu le 15 septembre 2026, au commit `81ecb25`. Consulter le [registre d'avancement](progress.md) pour les tickets implémentés et leurs vérifications. Les descriptions ci-dessous conservent leurs critères initiaux ; les fichiers à créer, signatures et commandes marqués « cible » ne sont pas une preuve de livraison.

## Commencer ici

Lire [AGENTS.md](../AGENTS.md), la [vision](vision.md), l'[architecture](architecture.md), puis les [contrats actuels](contracts.md). Exécuter T00, puis coder uniquement T01 sur une branche `codex/manual-world-control`. Livrer ce premier changement avec ses tests avant de passer à la suite.

Le premier résultat attendu est simple : un développeur peut consulter les capacités du monde et lui envoyer une action de son choix, sans lancer `demo.py`. Aucun modèle IA ni moteur graphique n'est nécessaire à ce ticket.

Pour chaque ticket :

1. Vérifier ses dépendances et lire les fichiers indiqués.
2. Implémenter le périmètre demandé. Si un comportement public change, mettre sa documentation à jour dans le même changement.
3. Vérifier les cas d'acceptation. Un résultat produit par un doublon de test ne valide pas une intégration réelle.
4. Livrer un changement relisible avec le résultat, les commandes de vérification et les limites restantes. Découper les tickets de mouvement et d'intégration en plusieurs contributions si nécessaire.
5. Mettre le statut à jour avec un lien vers la contribution et ses preuves. « Implémenté », « vérifié sur CPU » et « vérifié avec le modèle réel » sont trois informations différentes.

Un blocage externe n'autorise pas à inventer une API, un squelette, des performances ou un succès. Consigner ce qui manque et poursuivre un ticket dont les dépendances sont disponibles. Les corrections locales et les tests du périmètre n'exigent pas une nouvelle décision produit.

## Ce que le code fait déjà

| Fichier existant | Rôle actuel | Conséquence pour la suite |
|---|---|---|
| [`catalog.py`](../src/promethee/catalog.py) | Capacités logiques et monde initial vide | Ce catalogue ne contient ni modèle 3D ni animations |
| [`world.py`](../src/promethee/world.py) | Validation et mutation d'une copie du monde | Les déplacements sont instantanés et sans collisions |
| [`runtime.py`](../src/promethee/runtime.py) | SQLite, commandes idempotentes, plans persistés | Un `ok: true` atteste seulement une transition logique |
| [`demo.py`](../src/promethee/demo.py) | Plan déterministe de sept actions | Réservé aux tests ; ne pas le donner au futur agent |
| [`cli.py`](../src/promethee/cli.py) | Commandes `demo`, `world`, `journal` | Aucune commande générique d'action n'existe encore |
| [`journal.py`](../src/promethee/journal.py) | Export Markdown des réussites logiques | Aucune recherche mémoire ni synthèse par un agent |
| [`test_runtime.py`](../tests/test_runtime.py) | Rejets, concurrence, reprise, atomicité, exports | Conserver ces garanties en faisant évoluer les contrats |

Le paquet utilise Python 3.12+, SQLite et aucune dépendance d'exécution externe. La CI couvre Windows/Linux et Python 3.12/3.13. Le schéma du monde est en version 1 ; aucune migration n'existe. `events()` lit aujourd'hui tout le registre. Il n'existe aucun serveur, contrôleur continu, agent, voix ni rendu dans Promethee.

## Ordre de travail

| Ticket | Résultat livrable | Dépendances | Jalon |
|---|---|---|---|
| T00 | Installation reproductible et état de départ vérifié | Aucune | M0 |
| T01 | Pilotage manuel d'actions libres | T00 | M0 |
| T02 | Essai ARDY et décision de rendu documentés | T00, matériel et accès au modèle | M1 |
| T03 | Provenance des mondes, révisions et migrations | T01 | M0 → M1 |
| T04 | Exécutions suivies jusqu'à un résultat confirmé | T03 | M1 |
| T05 | Annulation et reprise après panne | T04 | M1 |
| T06 | Monde et squelette visibles | T02 | M1 |
| T07 | Mouvement réel relié à l'état du monde | T05, T06 | M1 |
| T08 | Interactions avec des objets du catalogue | T07 | M3 |
| T09 | Agent Hermes pilotant le monde par texte | T07 | M2 |
| T10 | Mémoire consultable et corrigible | T09 | M3 |
| T11 | Conversation vocale et interruptions partagées | T09, T10 | M2 |
| T12 | Initiative configurable, sans activité imposée | T08, T10, T11 | M4 |
| T13 | Extension ou RL justifié par une limite observée | Limite mesurée sur les capacités précédentes | M5 |

T02 peut avancer séparément de T01 et T03–T05. Si le GPU ou l'accès au modèle manque, T03–T05 restent faisables avec un contrôleur de test. T06 peut commencer dès que T02 est conclu. Les tickets suivants peuvent être préparés avec des doublons, mais leur validation réelle conserve les dépendances du tableau.

Les jalons produit ne sont pas un ordre strict de commits : la mémoire est raccordée avant la voix complète pour ne pas créer deux historiques indépendants. Aucun calendrier de livraison ne peut être fiable avant l'essai moteur T02.

## T00 — Vérifier le point de départ

**À lire :** `pyproject.toml`, `.github/workflows/ci.yml`, `tests/test_runtime.py`.

Depuis la racine du dépôt, dans un environnement neuf ou synchronisé :

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv build
```

Pour constater la persistance, utiliser un dossier de test neuf avec l'option existante `--data-dir`, lancer `demo --pause-after 4`, fermer le processus, puis `demo --resume` dans ce même dossier. Constater la fin du plan et l'absence de doublons. Ne pas utiliser les données d'une session personnelle.

**Terminé quand :** les vérifications passent et les versions Python/uv utilisées sont notées dans la contribution. Si un test échoue déjà, conserver son erreur exacte avant toute modification ; ne pas le supprimer pour obtenir du vert.

Sous Windows, si le répertoire temporaire système refuse l'accès, utiliser `pytest --basetemp` avec un dossier neuf dédié, résolu à l'intérieur de `.local/`. Pytest efface ce dossier : ne jamais lui donner la racine du projet ou un dossier de données. Ce contournement local ne justifie pas de modifier les tests métier.

## T01 — Piloter le monde sans scénario

**À modifier :** `src/promethee/cli.py`, `docs/contracts.md`, `README.md`.
**À créer :** `tests/test_cli_actions.py`.

Ajouter deux commandes cibles, sans dépendance supplémentaire :

- `catalog` retourne les assets et leurs capacités sous forme JSON, sans créer d'objet ni démarrer d'activité.
- `act --request-id <id> --file <fichier.json>` lit une action UTF-8 au format existant `{kind, args}` et appelle `Runtime.execute`. `--data-dir` reste une option globale, placée avant la sous-commande.

La validation métier reste dans `world.py` et `runtime.py`. Ne pas recopier leurs règles dans la CLI. Ne pas ajouter d'interpréteur de langage naturel, de génération automatique d'ID ou de plan caché.

Codes de sortie cibles : `0` pour un résultat logique réussi ou rejoué avec succès ; `1` pour une action rejetée avec `ok: false` ; `2` pour un fichier illisible, du JSON mal formé ou une erreur d'entrée. Un rejet rejoué garde le code `1`. Une panne de stockage reste une erreur technique, jamais une réussite.

**Vérifications en sous-processus :**

- Le catalogue est lisible et aucun objet ni plan n'apparaît.
- Une action valide choisie par le test modifie exactement l'état attendu ; elle n'importe pas le plan `STEPS`.
- La même requête relancée dans un nouveau processus ne produit aucun effet supplémentaire.
- Un même ID avec un autre contenu est refusé ; un rejet métier retourne `1` et laisse le monde inchangé.
- Un fichier absent ou mal formé retourne `2`, sans nouvelle action enregistrée.

**Terminé quand :** ces commandes permettent d'agir dans un monde vide sans appeler `start_activity`. Les commandes `demo`, `world` et `journal` restent fonctionnelles. Le README explique que ce pilotage est encore logique et instantané.

## T02 — Lever l'incertitude sur le mouvement

**À créer :** `docs/decisions/001-motion-stack.md` et, si nécessaire, `experiments/motion/README.md`. Les poids, installations et résultats restent dans un environnement séparé et des dossiers locaux ignorés.

Commencer par le [dépôt officiel ARDY](https://github.com/nv-tlabs/ardy) et sa [présentation technique](https://research.nvidia.com/labs/sil/projects/ardy/), consultés le 15 septembre 2026. Le dépôt annonce des checkpoints Core et G1 et un visualiseur de démonstration ; son environnement principalement testé est Ubuntu 22.04, Python 3.11 et RTX 4090. L'encodeur de texte dépend d'un modèle Hugging Face à accès contrôlé. Ces indications ne constituent pas une validation sur notre machine.

**Travail :**

1. Relever OS, architecture CPU, GPU, VRAM, pilote et accès effectif aux composants nécessaires. Vérifier séparément licences du code, des poids, de l'encodeur et des assets.
2. Fixer la révision du dépôt et le checkpoint essayé. Installer dans un environnement indépendant : ne pas forcer le Python ni les dépendances lourdes du modèle dans le paquet CPU.
3. Charger le modèle dans son visualiseur officiel avant de construire un rendu Promethee. Vérifier la génération, un changement d'instruction et une contrainte spatiale accessibles dans la version essayée.
4. Relever les conventions réellement utilisées : liste et hiérarchie des articulations, unités, axes, sens des rotations, ordre des quaternions, cadence des poses et représentation de la racine.
5. Mesurer séparément chargement à froid, encodage du texte, première pose exploitable, génération des blocs suivants et mémoire utilisée. Ne pas confondre FPS d'affichage et vitesse de génération.
6. Conserver localement les commandes exactes, paramètres, graines, traces et captures. Varier départs, cibles et instructions ; utiliser des cas distincts pour la calibration et la vérification.

**Décision attendue :** choisir le visualiseur déjà disponible pour le premier rendu s'il permet l'essai nécessaire. Ne retenir un autre moteur que pour un besoin concret absent, avec un essai d'import du squelette. Écrire le choix, les conventions, les mesures locales consultables et les limites ; ne pas dresser un comparatif théorique de dix moteurs.

**Terminé quand :** un second développeur peut reproduire l'essai sur l'environnement décrit et comprendre si la génération peut alimenter un corps interactif. L'absence d'accès ou de matériel donne le statut « bloqué », jamais « validé avec des animations de remplacement ». Elle n'empêche pas T03–T05.

Cet essai sélectionne un moyen de produire des poses. Une pose plausible ne suffit pas à valider collision, équilibre ou manipulation d'objet ; ces capacités seront mesurées dans T07–T08.

## T03 — Distinguer les données et versionner le monde

**À modifier :** `runtime.py`, `catalog.py`, `cli.py`, `journal.py`, `docs/contracts.md`, `docs/memory.md`.
**À créer :** `src/promethee/migrations.py`, `tests/test_migrations.py`, `tests/test_data_origin.py`.

Introduire une migration explicite du schéma 1 vers 2. Ajouter au monde :

- `data_origin` : `fixture`, `session` ou `legacy`. Une ancienne base sans provenance devient `legacy`, sans déduction à partir de ses objets.
- `revision` : entier commençant à `0` après création ou migration, augmenté dans la même transaction que chaque modification effective du monde. Ce compteur ne compte ni les lectures, ni les retransmissions, ni les rejets.

Les nouveaux mondes de démonstration et de tests sont `fixture`. Une future session d'agent sera créée explicitement avec `session`, une base neuve et un coffre distinct. L'origine est persistée, non modifiable par une action de l'avatar ; rouvrir une base ne doit pas la réétiqueter. Les points d'entrée de l'agent et de sa mémoire refuseront `fixture` et `legacy`. La commande `demo` doit refuser une base `session`.

Préserver `world_id`, objets, commandes, résultats, activités et notes existantes. Ne pas transformer un `ok` historique en résultat 3D. Prévoir une sauvegarde vérifiée avant la migration explicite ; son échec doit laisser la base utilisable dans l'ancien schéma. Les versions inconnues restent refusées. Tout changement ultérieur de stockage emprunte ce même mécanisme.

**Terminé quand :** une base v1 avec un plan suspendu et un rejet se migre sans perte, peut reprendre ce plan, et une seconde migration n'ajoute rien. Une panne pendant la migration annule ses modifications. Deux mutations concurrentes donnent des révisions cohérentes. L'origine de la base figure dans les nouveaux exports ; les notes modifiées à la main restent intactes.

## T04 — Suivre une action jusqu'à son résultat

**À modifier :** `runtime.py`, `world.py`, `docs/contracts.md`, le mécanisme de migration de T03.
**À créer :** `src/promethee/execution.py`, `tests/test_execution.py`, un contrôleur factice dans `tests/`.

Implémenter une nouvelle voie d'exécution pour le corps. Conserver `Runtime.execute` et les plans instantanés comme outils du monde logique, réservés aux données de test ou historiques. Ils ne doivent pas permettre de contourner le contrôleur d'une session réelle.

Contrat cible de soumission : `request_id`, `expected_revision`, `action` au format `{kind, args}`. La révision attendue est obligatoire ; le runtime valide la requête et sa compatibilité avec l'état courant avant de l'accepter. La relecture d'un ID déjà enregistré précède le contrôle de révision ; elle rend son état courant sans nouvel envoi. Un même ID avec une enveloppe différente est refusé.

| État cible | Signification et transitions possibles |
|---|---|
| `rejected` | La demande n'est pas admissible ; aucun envoi au contrôleur |
| `accepted` | Demande enregistrée ; peut devenir `running`, `failed`, `cancelled` ou `interrupted` |
| `running` | Exécution attestée ; peut devenir `completed`, `failed`, `cancelled` ou `interrupted` |
| `completed` | Le contrôleur a confirmé le résultat avec un état final valide |
| `failed` | L'exécution a échoué avec une cause connue |
| `cancelled` | L'annulation a été confirmée, ou a précédé tout envoi |
| `interrupted` | L'exécution n'a pas de résultat final fiable, par exemple après une panne |

Les états terminaux ne sont pas réouverts. Une nouvelle tentative exige un nouvel ID. Une demande d'annulation pendant `running` est un indicateur `cancel_requested`, pas immédiatement un résultat `cancelled`.

Prévoir quatre opérations Python distinctes dans `execution.py` : soumettre, lire l'exécution par ID, demander l'annulation et enregistrer un retour du contrôleur. Les noms exacts sont documentés dans les contrats à la livraison. Stocker ce suivi dans des tables dédiées avec une migration ; ne pas détourner le champ `ok` des anciennes commandes pour y cacher les nouveaux états.

Pour cette première version, une seule action modifiant le monde peut être en cours. Les autres mutations sont rejetées avec `busy`, sans file d'attente cachée ; lectures et annulation restent possibles. Appliquer cette règle à toutes les entrées, y compris la CLI. Ne pas construire de gestionnaire de ressources concurrentes avant un besoin mesuré.

Les retours du contrôleur portent au minimum l'ID de requête, l'identifiant de sa session, un numéro de séquence monotone et leur provenance (`logical-test`, `kinematic` ou `physics`). Un retour répété, ancien ou appartenant à une autre session ne modifie rien. Le contrôleur de test est injecté explicitement ; il ne simule pas une intégration livrée.

L'opération qui enregistre ces retours est réservée au pilote du corps. Elle n'est jamais exposée comme outil à l'agent ; la provenance est attribuée par l'adaptateur, pas déclarée par un prompt.

**Terminé quand :** une soumission n'avance pas l'avatar ; seuls des retours validés mettent son état à jour. L'enregistrement du résultat, de l'événement et du monde est atomique. Les tests couvrent rejet, conflit de révision, `busy`, doublon de demande, doublon de retour, échec et réussite. Aucun import GPU n'est nécessaire.

Les plans séquentiels actuels ne sont pas branchés au corps dans ce ticket. Si des plans asynchrones sont ajoutés plus tard, leur curseur ne pourra avancer qu'après `completed`, dans la même transaction. Une interruption ou un abandon ne vaut jamais réussite.

## T05 — Gérer annulation, panne et redémarrage

**À modifier :** `execution.py`, `runtime.py`, `journal.py`, `docs/contracts.md`.
**À créer :** `tests/test_execution_recovery.py`.

Donner au contrôleur factice de T04 une horloge pilotée par le test, des points de progression et un accusé d'annulation. Ne pas utiliser des délais réels pour rendre les tests « asynchrones ».

**Travail :**

- Persister l'intention avant l'envoi. Ne pas garder une transaction SQLite ouverte pendant un appel au contrôleur ou à un modèle.
- Annuler immédiatement une requête qui n'a jamais été envoyée. Après envoi, demander l'arrêt et attendre son retour ; conserver la dernière pose confirmée.
- Si l'arrêt n'est pas confirmé avant le délai configuré, passer à `interrupted`, marquer l'état du corps comme non confirmé et refuser de nouvelles mutations jusqu'à réconciliation.
- Au redémarrage, réconcilier toute exécution non terminale avec la session du contrôleur. Si son état est inconnu, ne pas réémettre automatiquement la commande ; conserver `interrupted` et la dernière observation avec sa date.
- Réserver la conduite du corps à un seul processus par monde. Un second pilote est refusé avant tout envoi. La perte de cette propriété déclenche la même récupération ; ouvrir une connexion SQLite ne suffit pas à devenir propriétaire du contrôleur.
- Refuser les retours tardifs d'une ancienne session. Une demande d'arrêt répétée reste sans nouvel effet.
- Adapter le journal : une demande acceptée, interrompue ou annulée ne produit pas une note de réussite. Les faits d'échec peuvent être conservés avec leur statut explicite.

**Terminé quand :** les tests coupent le processus avant l'envoi, après l'envoi, pendant la progression et avant l'écriture du résultat final. Aucun cas ne crée une double action ou un succès inventé. Annulation et complétion concurrentes aboutissent à un seul résultat terminal, selon l'ordre effectivement enregistré.

SQLite garantit l'atomicité locale, pas une exécution physique « exactement une fois » à travers une panne. La stratégie de récupération doit rendre l'incertitude visible ; un état final souhaité ne remplace pas une observation.

Pour sortir de cet état, acquérir une nouvelle observation complète du corps et du monde concerné, la valider puis la persister. L'ancienne exécution reste `interrupted` dans l'historique ; les nouvelles actions utilisent de nouveaux IDs. Documenter et tester ce chemin de récupération, sans demander au développeur d'éditer SQLite à la main.

## T06 — Afficher le monde et un squelette

**À créer après T02 :** un petit adaptateur de visualisation et `docs/rendering.md`. Mettre son chemin et sa commande exacte dans la décision T02 ; ne pas créer maintenant des projets Unity, Unreal et web en parallèle.

Lire le snapshot et afficher les instances par leur ID stable, avec un sol et un humanoïde de test. Le rendu commence en lecture seule. S'il manque un asset, montrer un repère identifié au lieu d'inventer un objet ou une animation. L'apparence de test ne fixe pas l'identité finale.

Décrire et centraliser la conversion entre le plan logique `[x, y]` et les axes du moteur choisi. Une distance d'un mètre doit rester un mètre. Vérifier origine, déplacement sur chaque axe, orientation et pose de repos sur le squelette réel. Ne pas changer silencieusement le format 2D des commandes v1.

**Terminé quand :** plusieurs dispositions créées manuellement se retrouvent aux mêmes positions après réouverture ; l'affichage d'un mouvement enregistré conserve échelle et articulations. Le rendu n'écrit pas dans SQLite et ne décide jamais qu'une action a réussi. Le paquet CPU s'installe toujours sans les dépendances du visualiseur.

Un seul titre par bloc d'interface. Les contrôles servent à observer et piloter ; aucun panneau de « pensées », « besoins » ou récit de vie n'est ajouté.

## T07 — Relier le mouvement réel au runtime

**À créer :** l'adaptateur du contrôleur choisi, des tests de conversion et `docs/motion-validation.md`.
**À modifier :** `execution.py`, rendu T06, contrats et dépendances optionnelles nécessaires.

À partir du code réellement testé dans T02, relier soumission, démarrage, progression, fin et annulation. Commencer par une capacité de déplacement vers une cible, puis un changement de posture. Les cibles et les paramètres de l'intention sont résolus depuis le monde ; un texte seul ne prouve pas que la géométrie a été respectée.

Le contrôleur renvoie les poses obtenues. Ne jamais appeler l'ancien `apply(move)` pour téléporter l'avatar à la destination au moment où le mouvement est seulement demandé. La cible finale et la pose observée restent deux données distinctes.

Documenter le format des poses et des observations après T02, puis étendre le schéma par migration si nécessaire : la position au sol v1 ne suffit pas à représenter toutes les articulations. Un horodatage et une indication de fraîcheur accompagnent la dernière observation connue ; ne pas la présenter comme actuelle après une perte du contrôleur.

Garder la boucle de poses indépendante des appels au modèle de raisonnement. Utiliser le mécanisme de communication minimal imposé par les environnements retenus ; des environnements Python incompatibles justifient un processus séparé, pas un système de microservices. Le runtime reste l'unique écrivain du monde persistant. Les poses d'affichage peuvent être éphémères ; persister des points confirmés et le résultat terminal sans écrire chaque image dans SQLite.

Ajouter à ce stade une commande cible `run` pour ouvrir explicitement une session et son rendu, avec le contrôleur choisi. Un monde neuf part vide ; un monde `fixture` ou `legacy` est refusé. Des contrôles manuels permettent de soumettre une action, voir son état et demander son arrêt via T04–T05. La CLI logique `act` ne constitue pas un raccourci pour modifier cette session. Fournir la commande de lancement exacte et une procédure courte de reprise après panne.

**Vérifications réelles :** départs et destinations variés, changement de consigne, interruption à plusieurs moments, cible inaccessible et perte du contrôleur. Mesurer erreur à la cible, latence, discontinuités, glissement des pieds et pénétrations. Fixer les seuils après calibration et les vérifier sur d'autres cas. Garder les vidéos locales et leur configuration.

**Terminé quand :** le résultat visible, l'état du runtime et l'historique décrivent la même exécution. Le mode cinématique est identifié comme tel ; une sortie ARDY ne vaut pas preuve de simulation physique. Une interruption aboutit à une pose confirmée ou à un état `interrupted` explicite.

## T08 — Donner des usages vérifiables aux objets

Préparation livrée : [portée géométrique du bras Core](arm-reaching.md), avec
douze essais locaux et inspection VRM d'une cible haute. Ce calcul n'est pas
une prise et n'est pas exposé au contrôleur. T08 reste ouvert.

Le [contrat d'observation des objets en 3D](spatial-objects.md) persiste aussi
les attachements à la main et vérifie leur cohérence après interruption dans
des tests CPU. Le contrôleur et le rendu d'interaction restent à raccorder.

**À modifier :** catalogue, validation, contrôleur et rendu.
**À créer :** tests des interactions et fiche de provenance pour chaque asset introduit.

Prendre une capacité à la fois : support d'une posture, transport d'un objet ou modification d'une surface. Le choix des objets sert la couverture technique ; aucun objet n'est obligatoire dans une session. Chaque entrée rendue relie asset visuel, capacités réellement disponibles, géométrie et points d'interaction dans les conventions de T02.

Ne pas conserver la portée arbitraire d'un mètre comme garantie anatomique. Vérifier les préconditions sur le corps utilisé. Une prise cinématique par attachement doit être décrite comme telle ; ne pas annoncer une prise physique validée. Rendre un objet ne lui donne pas automatiquement toutes les capacités de son homologue logique.

**Terminé quand :** objets déplacés, cibles absentes, mains occupées et interruptions sont correctement traités, avec des essais sur plusieurs positions et géométries. Le corps, l'objet tenu et les événements restent cohérents. Une collision ou une impossibilité n'est pas « corrigée » en écrivant directement le résultat souhaité dans la base.

## T09 — Brancher Hermes en conversation textuelle

**À créer :** `src/promethee/mcp_server.py`, `docs/hermes-setup.md` et tests du pont d'outils. Introduire le SDK nécessaire en dépendance optionnelle avec sa version testée.

Le point d'intégration retenu pour commencer est un petit serveur MCP local en stdio : [Hermes documente ce transport](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp). Le serveur traduit des appels d'outils vers le runtime existant ; il ne recrée ni boucle de raisonnement ni mémoire de Hermes.

Raccorder ce pont à l'exécuteur de T07, dans son processus ou par la liaison locale déjà retenue. Ne pas instancier un second contrôleur, recréer une base ou recharger le modèle moteur à chaque appel d'outil. Si le serveur est relancé, appliquer la récupération T05 avant d'accepter de nouvelles mutations.

Outils cibles : lire le monde et sa révision, lister les capacités actives, soumettre une action, lire son état, demander son annulation. Le transport MCP ne change ni les validations ni l'idempotence. L'ID d'action métier est stable entre retransmissions ; il ne doit pas être remplacé à chaque nouvel échange réseau.

Créer un profil Hermes dédié à Promethee avec une base `session` et un coffre neufs. Ne pas charger le dépôt comme contexte de vie de l'avatar : `AGENTS.md`, `demo.py`, les tests et ce plan s'adressent au développeur. Exposer les contrats utiles par les descriptions d'outils. Ne pas importer les souvenirs d'un autre projet.

Vérifier dans la version retenue de Hermes le raccord réel au fournisseur et l'accès au modèle souhaité. Astra reste la cible de raisonnement ; sa présence dans Codex ne garantit pas l'accès API. Noter le modèle effectivement utilisé. Si l'accès manque, garder les tests avec doublon et signaler l'intégration réelle non validée ; aucun remplacement silencieux.

Limiter ce profil aux capacités utiles au monde et à sa mémoire. Il n'a pas besoin d'un terminal généraliste ou de modifier le code du projet pour déplacer l'avatar. Pas d'appel LLM par image, pas d'initiative périodique avant T12, pas de deuxième agent qui décide indépendamment des actions.

**Terminé quand :** le vrai agent peut converser sans action, lire un état, demander une capacité disponible et rapporter son résultat observé. Les tests couvrent arguments mal formés, modèle indisponible, délai dépassé, correction utilisateur et réponse tardive devenue obsolète. Une action seulement `accepted` n'est jamais racontée comme terminée.

Pour les interruptions, associer les décisions à un tour de conversation et invalider les propositions devenues obsolètes avant leur soumission. Les tests avec doublon vérifient cette règle ; des conversations variées vérifient le raccord réel sans noter la conformité à un scénario.

## T10 — Rendre la mémoire utilisable

**À modifier :** `journal.py`, pont Hermes et `docs/memory.md`.
**À créer :** `src/promethee/memory.py`, tests de recherche, provenance et corrections.

Commencer par les notes Markdown et une recherche locale simple, bornée en nombre de résultats et en taille. Ne pas ajouter une base vectorielle avant d'avoir observé les limites de cette recherche. Chaque résultat indique sa source, sa date et les événements ou messages qui le fondent.

Lire l'état actuel des objets dans le runtime. Une ancienne note ne peut pas contredire ce snapshot. Distinguer observations, propositions, résumés et préférences incertaines. Une correction reste liée au contenu corrigé et apparaît dans les résultats futurs. Aucun résumé ne crée de souvenir sans source.

Le pont mémoire refuse toute base `fixture`/`legacy` et tout coffre de démonstration. Vérifier la provenance des notes importées ; des notes sans provenance restent à l'écart de l'ingestion automatique. Éviter de dupliquer le même historique dans Hermes et Obsidian : documenter ce qui reste dans le contexte compact et ce qui est retrouvé à la demande.

**Terminé quand :** la recherche fonctionne aussi avec un historique vide, une note corrigée, un objet disparu et plusieurs mondes. Les sources de test ne passent pas dans une session. Les textes des objets et notes restent des données, sans exécution de commandes. Retrouver un projet n'en déclenche pas automatiquement la reprise.

## T11 — Ajouter la voix au même agent

**À créer :** adaptateur vocal, tests des interruptions et documentation de configuration. Vérifier d'abord les interfaces actuelles et les accès décrits dans [les intégrations](integrations.md) ; les noms d'API ne doivent pas être inventés à partir d'un nom commercial.

Raccorder audio entrant, délégation au même contexte Hermes et audio sortant. La piste GPT-Live reste à vérifier avec le compte cible. Une chaîne transcription → Hermes → synthèse peut servir au diagnostic ; préciser laquelle fonctionne réellement. Garder le mode texte utilisable.

Séparer deux événements : interrompre une réponse vocale et arrêter une action du corps. Une prise de parole de l'utilisateur coupe l'audio sortant ; elle ne téléporte pas l'avatar et n'annule pas automatiquement toute activité. Un arrêt explicite du corps passe par T05. L'invalidation des décisions obsolètes passe par T09.

**Terminé quand :** interruption pendant l'écoute, le raisonnement, la parole et le mouvement ; microphone absent ; fournisseur indisponible ; fin tardive d'une ancienne réponse. Aucune parole obsolète ni double commande ne repart. Mesurer le délai jusqu'à la réponse utile, le délai de coupure et les coûts d'une session de test. Le dialogue distingue action prévue, en cours et confirmée.

## T12 — Ouvrir l'initiative

**À créer :** `src/promethee/initiative.py`, tests avec horloge contrôlée et configuration documentée.

Activer explicitement l'initiative par session. Les réveils proviennent d'événements pertinents et, si configuré, d'une cadence limitée. Persister un budget d'appels et une pause utilisateur ; regrouper les événements qui arrivent pendant une décision. Ne jamais empiler des appels parce qu'un modèle répond lentement.

L'agent peut proposer une intention, la modifier, l'abandonner ou ne rien lancer. Aucun projet, désir, besoin physiologique ou usage d'objet n'est préchargé pour susciter une conduite attendue. Les contraintes portent sur l'exécution et le budget, pas sur une quantité minimale d'activité.

**Terminé quand :** les tests prouvent le respect du budget, la pause après redémarrage, l'absence de doublons et le traitement des décisions obsolètes. Les observations réelles couvrent sessions sollicitées et non sollicitées, historiques différents et capacités retirées. Examiner les répétitions insensibles au contexte ; ne pas récompenser artificiellement la nouveauté ou l'agitation. L'inactivité n'est, à elle seule, ni un échec ni une réussite.

## T13 — Étendre à partir d'une limite mesurée

Ce ticket n'est pas une autorisation de lancer un entraînement complet ou d'installer tous les connecteurs. Ouvrir une tâche distincte pour chaque capacité nouvelle, avec le problème observé et son bénéfice attendu.

Pour une limite motrice, conserver d'abord un cas qui échoue et comparer les correctifs simples : géométrie, conversion, contraintes, retargeting ou contrôleur existant. Si le RL devient pertinent, définir environnement, observations, actions, terminaison, récompenses, données et coût maximal avant le premier entraînement. Séparer les situations d'entraînement de celles d'évaluation et lancer un essai court avant un long run. Ne pas importer les contrats du robot Microduck dans cet humanoïde virtuel.

Les récompenses portent sur la capacité évaluée, pas sur une routine de vie ni sur l'exécution de la démonstration. Conserver versions, graines, coûts, checkpoints et vidéos permettant de comparer au système précédent. Une interaction avec un service externe définit séparément les actions disponibles et leur périmètre utilisateur.

## Critères communs pour livrer

- Le ticket produit un comportement observable et ses erreurs sont explicites. Une interface vide ou un `TODO` ne valide rien.
- Les tests CPU nécessaires passent, ainsi que `ruff check`, `ruff format --check` et la construction du paquet. Une intégration optionnelle n'alourdit pas l'installation de base. Les versions effectivement testées sont fixées dans les dépendances et leur verrouillage.
- Pour les changements de stockage : migration, reprise, idempotence et rollback sont couverts. Pour le corps : observation visuelle et contacts. Pour le modèle : essais réels distincts des doublons.
- Les traces corrèlent monde, requête, exécution et source ; elles ne contiennent pas de secrets. Les données de session, modèles et vidéos restent locaux selon [CONTRIBUTING.md](../CONTRIBUTING.md).
- Les contrats, commandes et limites documentés correspondent au code livré. Le ticket suivant peut être repris sans supposer qu'un composant manquant fonctionne déjà.

Format de compte rendu à joindre à chaque contribution : **ticket et résultat**, **fichiers concernés**, **vérifications exécutées et observations**, **limites ou blocages**, **prochain ticket débloqué**. Une ou deux phrases par point suffisent lorsque le changement est simple.
