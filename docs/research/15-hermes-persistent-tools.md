# Hermes : conserver la connexion aux outils

Recherche parallèle du 16 septembre 2026. Elle prolonge le
[diagnostic des lectures et actions](14-hermes-tool-latency.md), dont les
seconds tours consacraient 1,70–1,71 s à rouvrir MCP. Ce temps est distinct
du raisonnement, de la génération vocale et de l'animation.

## Ce que le code natif permet

Sources inspectées : Hermes **0.21.3**, commit
`2179a279ae04bfadf8efbc49a01ca0abfb738000`, MCP **2.0.0**.
La [documentation MCP d'Hermes](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp)
décrit découverte, filtres et connexions. Le code apporte une précision
nécessaire à notre intégration :

- `run_conversation(task_id=...)` transmet l'identifiant fourni par l'hôte
  jusqu'au handler d'outil. Le chemin séquentiel et les lots parallèles
  capturent cette valeur pour chaque appel.
- Le [handler MCP](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/tools/mcp_tool_handlers.py)
  reçoit cet identifiant, mais ne le transmet pas dans `ClientSession.call_tool`.
  Garder simplement le processus ouvert ferait perdre notre ancienne liaison
  entre processus et tour.
- Le [registre](https://github.com/NousResearch/hermes-agent/blob/2179a279ae04bfadf8efbc49a01ca0abfb738000/tools/mcp_tool_registration.py)
  recrée les handlers à travers leur factory après découverte ou reconnexion.
  Envelopper seulement le premier handler ne suffit donc pas.
- Le `Context` MCP est exclu du schéma envoyé au modèle, mais conserve les
  arguments bruts. Un champ supplémentaire peut ainsi transporter une identité
  fournie par l'hôte, sans la faire générer par le modèle.

Nous conservons le moteur Hermes, ses RPC, verrous, délais, règles de reprise
et son format de résultats. Les callbacks servent à mesurer ; ils ne sont pas
une interface d'autorisation. Le middleware natif examiné laisse continuer
certaines exceptions avant dispatch : il ne fournit pas seul le refus strict
requis ici. Aucun fork d'Hermes ou second moteur de décision n'est introduit.

## Raccord retenu

Les nouveaux profils résidents utilisent `--call-authority`. Avant discovery,
l'adaptateur enveloppe la factory native pour le seul serveur `promethee`.
Chaque appel capture son `task_id`, exige la forme `turn-` suivie de 32 chiffres
hexadécimaux minuscules, copie les arguments et ajoute `_promethee_turn_id`.
La présence préalable de ce champ est refusée, même si sa valeur est correcte.
Les autres serveurs gardent leur handler original.

Le serveur lit ce champ depuis le contexte de la requête et construit les
outils monde ou mémoire liés à cet identifiant. Il ne lit jamais le tour
courant pour remplacer une autorité manquante. Une mutation obsolète reste
refusée dans la transaction SQLite ; une retransmission identique déjà
enregistrée conserve son comportement idempotent, sans nouvel effet.
Les lectures gardent leur sémantique existante.

Après un succès, agent et connexion sont conservés. Chaque activation relit
l'historique et vérifie monde, tour actif, échéance, profil, authentification,
modèle, schémas et périmètre d'outils. Une interruption invalide le tour avant
de détruire le worker et ses descendants. Une erreur ou réponse partielle
interdit sa réutilisation. Les profils fixes `--turn-id` restent utilisés par
les workers jetables et disponibles au lancement manuel du serveur.

L'identifiant transporté n'est pas un secret : la confiance vient du worker
possédé par l'hôte, de son stdio privé et de la garde transactionnelle. Le
raccord utilise une interface privée versionnée. Alias, signature ou factory
remplacés provoquent un refus explicite ; une mise à jour Hermes doit être
requalifiée. Il ne s'agit pas d'une compatibilité garantie avec toute version.

La revue distingue aussi une limite native préexistante : une reconnexion
interne pendant un tour peut recréer un handler avant le prochain contrôle
du schéma par Promethee. L'identifiant d'appel reste protégé, mais le schéma
n'est pas revalidé à cet instant. Arrêter le résident avant de modifier les
sources ou versions des outils ; le redémarrage découvre alors leurs nouvelles
définitions. Le contrôle au début d'un tour ne garantit pas une mise à jour à chaud.

## Vérifications

Les tests utilisent notamment deux tours et deux soumissions avec le même
processus MCP réel, un appel retenu avant admission pendant le remplacement
du tour, expiration, annulation, mémoire sourcée et retransmissions. Ils
vérifient aussi arrêt des descendants, profil ou authentification modifiés,
schéma changé et historique frais. Les schémas publics n'exposent ni le
`Context` ni le champ d'autorité.

Un test optionnel charge le vrai registre et les handlers Hermes épinglés,
avec une session RPC simulée, sans modèle. Il vérifie deux enregistrements
successifs et les refus d'identité absente ou fournie dans les arguments.
Les essais avec fournisseur réel sont distingués de ces contrôles CPU.

Validation locale : **722 tests du socle réussis, 2 ignorés**, **331 tests de
la scène et 7 sous-tests réussis** ; Ruff, format et construction du paquet
réussissent. La CI optionnelle inclut maintenant les tests du transport
persistant et de l'hôte résident.

## Comparaison native

Baseline `b721e7e`, candidat figé, même Hermes, Luna `gpt-5.6-luna`, effort
`low`, instructions, outils et observation initiale. Deux mondes neufs de
qualification utilisent un contrôleur CPU statique : il accepte une posture
mais ne la joue jamais. Ni voix, ni GPU dans cette comparaison. La scène
publique reste au repos ; aucune batterie de tests ne tourne pendant les appels.

Le premier tour demande une posture ; le second relit monde et reçu sans
nouvelle action. L'ordre est A puis B, avec seulement deux tours par condition.
La préparation initiale est mesurée séparément : **7,91 s** pour A,
**7,85 s** pour B. Les vrais schémas natifs sont identiques, empreinte
`c45f13dd345ddd15357c55722c11def4dd2821aa6d15046f23f51164b340e737`.

| Condition | Tour | Message → résultat | Boucle native | Actualisation MCP | Appels modèle |
| --- | --- | ---: | ---: | ---: | ---: |
| A — reconnexion | 1 | 12,548 s | 12,389 s | 0,018 s | 3 |
| B — connexion conservée | 1 | 11,894 s | 11,833 s | 0,016 s | 3 |
| A — reconnexion | 2 | 9,820 s | 7,973 s | 1,695 s | 2 |
| B — connexion conservée | 2 | 7,909 s | 7,855 s | 0,012 s | 2 |

Le second tour économise **1,684 s sur l'actualisation MCP** dans cette paire.
Le temps total diminue de **1,911 s** ; la différence restante inclut notamment
la variabilité fournisseur et la fermeture désormais évitée. La boucle native
englobe les outils et plusieurs appels API, pas seulement l'inférence.
Aucun délai jusqu'au premier son, coût monétaire ou gain général n'est déduit.

Dans A, les deux tours ont des processus MCP différents ; dans B, ils
conservent le même lanceur et le même interpréteur. Les quatre tours utilisent
bien leurs nouvelles identités. Chaque monde contient exactement une action
acceptée, aucune exécution corporelle terminée et une pose inchangée. Les deux
relectures disent explicitement que la posture n'est pas encore observée.
Les demandes initiales contiennent des formulations adressées à l'utilisateur
(« à toi de jouer ») : cet essai de transport ne qualifie pas la mise en scène.
Les dix PID possédés par les deux essais sont absents après fermeture.

Une première campagne s'est arrêtée après un tour baseline réussi en **20,105 s** :
son contrôle comparait le PID du lanceur Windows à celui de l'interpréteur
enfant. Aucun deuxième tour ni candidat n'a été lancé dans cette campagne.
Elle est conservée comme essai incomplet, pas comme comparaison. Le contrôle
corrigé vérifie parenté, dates de création et sources avant chaque inférence,
puis impose la continuité ou le renouvellement des deux identités attendues.

Archives locales : `.local/hermes-transport-ab-01/` pour l'arrêt initial,
`.local/hermes-transport-ab-02/` pour manifest, snapshots de sources,
schémas natifs, requêtes visibles, résultats, chronométrage et audit des
processus. Le candidat publié possède les mêmes sources que le candidat figé.
