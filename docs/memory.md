# Mémoire et Obsidian

La mémoire utilise des notes Markdown et une recherche locale bornée. Elle ne
modifie pas les poids du modèle et n'importe ni identité, ni préférences, ni
scénario. Le monde courant reste la référence pour les objets ; une note décrit
un historique, une proposition ou une interprétation.

## Ouvrir une mémoire neuve

Le schéma 7 distingue les sessions `interactive`, `qualification` et non classées.
`init-session` crée un monde interactif vide, sans modèle ni contrôleur. `run`
classe aussi comme interactive une nouvelle session ouverte par l'interface
manuelle. Une session existante conserve sa classification. Les anciennes bases
migrées restent non classées et ne sont jamais promues automatiquement.

```sh
uv run promethee --data-dir .local/ma-session init-session
uv run --extra memory promethee --data-dir .local/ma-session memory-init --vault .local/mon-coffre
uv run --extra memory promethee --data-dir .local/ma-session memory-search --vault .local/mon-coffre --query ""
```

Utiliser un dossier de coffre qui n'existe pas. Son manifeste le lie à un seul
monde interactif. Les bases `fixture`, `legacy`, de qualification ou non classées
sont refusées. Un coffre existant, de démonstration ou lié à un autre monde ne
peut pas être réutilisé à l'initialisation. Copier une ancienne note ou son
frontmatter ne la rend pas admissible.

L'extra `memory` contient [PyYAML 6.0.3](https://pypi.org/project/PyYAML/6.0.3/),
également installé avec l'extra `agent`. La lecture utilise `safe_load`, refuse
les tags personnalisés et les alias YAML, et borne les fichiers. Aucun texte
de note ou d'objet n'est exécuté comme du code.

## Raccord à Hermes

Ajouter `--vault .local/mon-coffre` à la commande `chat` du [guide Hermes](hermes-setup.md).
Le profil expose alors neuf outils : les cinq opérations du monde et les quatre
opérations mémoire suivantes. Sans ce paramètre, il conserve les cinq outils
du monde. L'authentification ChatGPT native de Hermes permet maintenant les
essais avec Astra réel ; les qualifications antérieures avec fournisseur local
restent identifiées séparément ci-dessous.

| Outil | Usage |
|---|---|
| `search_memory` | Recherche dans les notes enregistrées et suit leurs corrections |
| `read_memory_note` | Lit la version corrigée d'une note connue, avec ses sources |
| `read_memory_source` | Relit un événement terminal ou un message du même monde |
| `write_memory_note` | Enregistre une note sourcée ou une correction, sous un ID stable |

Une retransmission conserve le même ID et le même contenu. Un ID avec un autre
contenu est refusé. Un ancien tour peut relire un résultat déjà accepté, mais
ne peut plus créer une nouvelle note après une correction conversationnelle.
La mémoire n'a aucun outil pour relancer un projet ou modifier le corps.

## Sources et catégories

Chaque note requiert une à huit sources existantes dans le monde associé :

- `user:TURN_ID` : message utilisateur conservé, même après une interruption ;
- `assistant:TURN_ID` : réponse native terminée, sans erreur ;
- `runtime:TURN_ID` : réveil d'initiative enregistré, distinct d'une parole humaine ;
- `execution:REQUEST_ID` : résultat terminal, avec statut et provenance du
  contrôleur. Un rejet reste un rejet, pas une action accomplie.

Le tour courant est visible dans `read_world.conversation`. Un assistant dont
l'appel est en cours, échoué ou périmé n'est pas une source admissible. Les
événements `logical-test` sont refusés. Les sources sont relues dans le registre,
pas validées sur la seule déclaration d'un fichier Markdown.

Les catégories sont `observation`, `proposal`, `summary`, `uncertain-preference`
et `correction`. Une parole de l'assistant peut fonder une proposition ou un
résumé, mais ne peut pas attester une observation. La présence de sources ne
prouve pas à elle seule que l'interprétation rédigée est juste : catégorie,
sources et incertitude restent visibles. Aucun résumé sans source n'est créé.

Un réveil d'initiative peut sourcer une proposition, mais pas une observation.
Le même tour ne peut pas être relu comme source `user:`. Les anciens messages
sans champ `trigger` conservent leur origine utilisateur initiale.

## Fichiers, éditions et corrections

Les notes se trouvent dans `Promethee/Memory/NOTE_ID.md`. Le frontmatter contient
monde, origine, catégorie, date, sources et éventuelle note corrigée. Une correction
ajoute un lien Obsidian vers sa version précédente. La base conserve l'enregistrement
original de publication pour vérifier cette provenance et reprendre un export
interrompu ; la recherche lit le texte Markdown.

Les modifications manuelles du titre ou du corps restent visibles et portent
`manually_edited: true` dans les résultats. L'export ne les écrase pas. Les tags
et changements de présentation YAML sont acceptés. Une modification des propriétés
de provenance met le fichier à l'écart. Les fichiers sans enregistrement
correspondant, déplacés ou renommés ne sont pas importés automatiquement.
Conserver leurs IDs et chemins pour la lecture par l'agent.

Une correction nomme la version actuelle qu'elle corrige ; les branches
concurrentes sont refusées. Les recherches sur les mots de l'ancienne version
renvoient la nouvelle, avec les IDs précédents. Si un fichier nécessaire à la
chaîne est absent ou invalide, la recherche ne ressuscite pas l'ancienne version.
Lire une note par son ancien ID suit aussi ses corrections.

L'enregistrement SQLite précède la publication atomique du fichier. Une panne
entre les deux laisse un export en attente, sans note partielle recherchable.
Une retransmission identique ou cette commande complète les fichiers manquants :

```sh
uv run --extra memory promethee --data-dir .local/ma-session memory-export --vault .local/mon-coffre
```

Cette commande recrée aussi un fichier enregistré puis supprimé ; elle ne remplace
jamais un fichier existant. Sauvegarder ensemble la base et le coffre. La
publication utilise un lien de fichier atomique dans le même dossier, vérifié
sur le système Windows local. Un système de fichiers qui ne le permet pas
signale une erreur et conserve l'enregistrement en attente.

## Bornes et autorité

Une recherche accepte 200 caractères et retourne au maximum cinq notes, avec
un extrait de 800 caractères chacune. Les résultats annoncent troncature,
sources, dates, corrections, éditions manuelles et existence d'autres résultats.
Ils incluent la révision et les objets courants du monde. `read_memory_note`
donne le contenu d'un fichier borné à 32 Kio ; une source est bornée à 4 000
caractères et annonce également sa troncature.

La création accepte un titre de 120 caractères et un texte de 4 000 caractères.
Le registre est limité à 1 000 notes et une chaîne à 16 versions. Il n'y a ni
effacement automatique, ni base vectorielle, ni recherche globale dans le disque.
Retrouver un projet ne le remet pas en activité.

L'historique natif reste dans `conversation_turns` et fournit le contexte court
de Hermes. Les notes gardent des références ciblées, sans recopier chaque
conversation dans Obsidian. La mémoire native globale de Hermes reste désactivée
pour ce profil ; seul ce coffre est disponible à la demande. Les profils
temporaires de qualification ne sont jamais importés.

## Journal d'exécution

`promethee journal --vault CHEMIN` conserve son rôle d'export déterministe sous
`Promethee/Observed/WORLD_ID/`. Il distingue succès logiques et résultats
corporels terminaux, avec origine, classification de session et mode du contrôleur.
Ces exports ne deviennent pas automatiquement des notes de mémoire enregistrées.
Les fichiers existants restent intacts, y compris les anciens exports sans
classification ; ils ne sont pas promus après migration.

## Vérifications

Les tests couvrent historique vide, correction retrouvée avec les anciens mots,
objet présent puis disparu, mondes et coffres distincts, sources absentes,
réponses inachevées, éditions Obsidian, tags YAML, fichiers excessifs, panne de
publication, rejeu, tour périmé et projet qui reste suspendu après lecture.
Les migrations v6 → v7 sont testées avec sauvegarde et rollback.

Le vrai transport MCP vérifie écriture, recherche et correction dans deux
processus successifs. `.local/hermes-memory-qualification-01` a aussi exercé le
profil à neuf outils dans le vrai Hermes, écrit puis retrouvé une note, et
conservé correction conversationnelle, délai maximal, erreur fournisseur et
reprise CLI. Son fournisseur est un doublon local, pas Astra. À la fin de cet
essai, son monde a été classé `qualification` et le refus d'accès à son coffre
a été vérifié. Ses textes restent des données de développement, pas une mémoire
personnelle. La syntaxe Obsidian est vérifiée par lecture YAML et liens ; aucune
revue visuelle dans l'application Obsidian n'est revendiquée.

## Essai avec Astra réel

Le script suivant utilise six appels réels à un modèle explicitement choisi,
dans deux mondes neufs. Il ne charge aucun coffre personnel, contrôleur corporel
ou périphérique audio. Ses messages fictifs sont des entrées de qualification,
pas des consignes initiales pour une session personnelle.

```sh
python experiments/agent/qualify_astra_memory.py --output .local/essai-memoire-astra-neuf --hermes-python CHEMIN_PYTHON_HERMES --hermes-root CHEMIN_HERMES --hermes-auth-root RACINE_AUTH_HERMES --model gpt-6-astra
```

Chaque message est traité après réouverture de l'hôte. Le script conserve les
réponses, appels d'outils natifs, notes, profils sans identifiants secrets et
sources du code dans le dossier de sortie. Les mondes exercent temporairement
le contrat interactif dans cet environnement isolé, puis sont classés
`qualification` dans un bloc de nettoyage, même si un appel échoue. Le refus
d'accès ultérieur à leur mémoire est vérifié. Ne pas réutiliser ces coffres
comme souvenirs personnels.

Un tour marqué `completed` prouve seulement la fin de l'appel. Il faut relire
les réponses et leurs sources avant de conclure sur la récupération, la
correction et l'absence d'action.

Le 15 septembre 2026, `.local/astra-memory-qualification-02` a terminé ses
six appels avec `gpt-6-astra`, Hermes 0.20.5 et le profil à neuf outils.
Les réponses et appels natifs relus montrent :

- une recherche vide reconnue sans souvenir inventé ;
- une proposition fictive suspendue enregistrée avec sa source utilisateur ;
- une correction liée, retrouvée en recherchant l'ancien terme, puis la source
  de cette correction relue par l'outil ;
- la distinction entre cette proposition historique et le monde actuellement
  vide, dont le corps non confirmé n'est pas présenté comme une observation physique ;
- une recherche vide dans le second monde, sans accès aux notes du premier.

Les latences de bout en bout sont respectivement 25,06 s, 36,54 s, 38,52 s,
30,18 s, 26,60 s et 40,75 s, chaque appel comprenant un démarrage de l'hôte.
Le premier coffre contient exactement deux notes — proposition et correction —,
le second zéro. Aucune exécution corporelle n'est enregistrée dans les deux
mondes ; leur exclusion ultérieure de la mémoire est vérifiée. Le premier
essai `01` s'est arrêté sur une erreur de préparation avant tout appel et ne
constitue pas une mesure du modèle.

Cette série vérifie un raisonnement réel sur les notes et un objet évoqué mais
absent. Le retrait d'un objet auparavant présent et les contenus malveillants
restent couverts ici par les tests déterministes, pas par cette série Astra.
Elle ne valide pas la qualité d'une mémoire sur une longue durée ni le rendu
visuel des notes dans Obsidian.
