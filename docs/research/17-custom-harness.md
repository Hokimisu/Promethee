# Essai d’Ariane sans Hermes

Qualification du 16 septembre 2026, à la demande de l’utilisateur après
l’[audit Hermes](16-hermes-avatar-audit.md). Le moteur `direct` appelle le même
modèle Luna, avec le même personnage et la même voix VoxCPM2, sans charger
la boucle, les prompts ou le code natif Hermes. Il reste expérimental.

## Résultat

La scène fonctionne avec cette boucle : trois répliques vocales lues,
bras levés puis baissés par ARDY, deux exécutions confirmées par le monde.
Le navigateur affiche bien les bras levés ; une observation de 13 secondes
confirme aussi une bouche animée pendant le son, puis refermée.

Le retrait d’Hermes n’élimine pas les délais du modèle. Sur les demandes
d’action, les lectures du monde et des capacités puis la soumission du geste
peuvent encore demander plusieurs allers-retours avant la réplique.

## Comparaison textuelle

Ordre fixé : Hermes résident, puis direct résident. Quatre demandes identiques
dans deux mondes de qualification neufs ; Luna `gpt-5.6-luna`, effort `low`,
même instruction Ariane et mêmes cinq outils. Contrôleur CPU statique,
sans génération de mouvement ni de voix. Chaque réponse et chaque échec sont
conservés ; aucune relance pour sélectionner une meilleure réponse.

| Demande | Hermes, texte complet | Direct, texte complet | Appels modèle directs |
| --- | ---: | ---: | ---: |
| Salutation | 5,81 s | 3,21 s | 1 |
| Plaisanterie sur une crêpe | 2,76 s | 2,95 s | 1 |
| Lever les bras, répondre sans attendre | 9,18 s | 15,05 s | 4 |
| Vérifier le résultat observé | 6,53 s | 7,72 s | 2 |

La préparation du résident prend respectivement 7,76 s et 1,70 s ; elle est
exclue de ces délais. Les deux agents distinguent correctement une commande
acceptée d’un geste confirmé : le contrôleur CPU de ce protocole n’exécute rien.

Cette petite série compare deux intégrations complètes. Le préambule natif
Hermes et les enveloppes de transport diffèrent ; ce n’est pas une mesure
isolée du coût de sa boucle. Pas de conclusion statistique ou tarifaire.
La variante directe fait moins de travail au démarrage, mais ne gagne pas
systématiquement pendant la conversation.

Preuves locales : `.local/custom-harness-ab-01-hermes/` et
`.local/custom-harness-ab-01-direct/`, avec manifestes, empreintes des sources,
préparation, résultats et mondes. Les quatre prévols de mise au point
`custom-harness-smoke-01` à `04` ont échoué sur le transport ou l’assemblage
SSE ; `05` réussit en 2,11 s. Ils sont conservés et exclus du tableau comparatif.

## Essai avec Vox et ARDY

Même référence vocale approuvée, CFG 2, dix pas, sortie 48 kHz ; un seul
processus Vox et un seul ARDY. Session neuve
`.local/realtime-direct-runs/session-5083dbf0aa6d/`.

| Demande | Texte prêt | Premier PCM après lancement Vox | Début de lecture navigateur¹ | Audio lu |
| --- | ---: | ---: | ---: | ---: |
| Salutation courte | 1,97 s | 0,20 s | 2,63 s | 4,32 s |
| Lever les bras et plaisanter | 11,26 s | 0,09 s | 11,71 s | 4,64 s |
| Baisser les bras et réagir | 8,82 s | 0,10 s | 9,50 s | 4,00 s |

¹ Depuis la création persistée du tour jusqu’à la réception serveur du reçu
`playback_started`. Cette mesure inclut le retour de télémétrie ; ce n’est
ni l’instant exact de sortie du haut-parleur ni une preuve d’écoute humaine.

Les trois reçus de lecture sont `completed`, sans sous-alimentation du tampon
audio. Les actions `salut-bras-1` et `baisse-bras-1` sont `completed`, source
`kinematic`. La lecture de la troisième phrase a été échantillonnée 130 fois :
40 échantillons avec son, poids maximal de bouche 0,900 puis retour à zéro,
poses reçues de séquence 2965 à 3171. Cela vérifie le raccord, sans certifier
la naturalité du geste, sa physique ou la qualité acoustique du matériel.

## Ce que fait la boucle maison

- Processus résident et connexion HTTP réutilisée ; au plus huit appels
  modèle par tour, sans relance automatique ni changement de modèle.
- Historique persistant fourni par l’hôte Promethee, avec conservation des
  identifiants d’appels et du contenu de raisonnement chiffré nécessaire au
  protocole. Aucun résumé de raisonnement n’est publié.
- Cinq outils du monde via les schémas MCP existants, appelés dans le processus.
  Chaque serveur est lié à un tour immuable ; SQLite conserve l’autorité sur
  les révisions, l’idempotence et les résultats d’exécution.
- Aucun outil ni audio déclenché depuis un delta incomplet. Les sorties SSE
  sont assemblées et admises seulement après un terminal réussi. Les doublons,
  réponses contradictoires, appels mal formés et tours obsolètes sont refusés.
- Même hôte de conversation, interruption, propriétaire des processus,
  direction vocale et lecteur PCM que la scène précédente.

Le SDK `httpx==0.28.1` est déclaré dans l’extra optionnel `agent`. La scène
utilise le compte OAuth déjà autorisé via un fichier explicitement configuré,
lu sans renouveler les jetons. Aucun secret n’est copié dans le dépôt.
Le protocole suit les [outils Responses](https://developers.openai.com/api/docs/guides/function-calling)
et les particularités de la route Codex observées dans le connecteur Hermes
épinglé. Cette route OAuth n’est pas présentée comme une API publique stable.

## Activation et limites

Dans une copie locale du fichier de configuration de la scène : ajouter
`"brain": "direct"` et `"auth_file": "chemin/vers/auth.json"`, supprimer
`hermes_python`, `hermes_root` et `hermes_auth_root`. Le reste du lancement
reste identique. Utiliser un nouveau `data_dir`, sans `resume_world`, pour
changer de moteur ; l’historique d’outils natif Hermes n’est pas converti.
Le choix par défaut reste `hermes` pour les configurations existantes.

Ce prototype ne fournit pas de renouvellement OAuth, de compaction longue
durée, de compétences Hermes ou de consolidation mémoire. La borne de
contexte est 512 Kio. Il n’expose que les cinq outils du monde, sans coffre
Obsidian dans cet essai. Un jeton expiré produit un échec explicite.

Le champ `first_text_seconds` des métriques privées mesure le premier delta
textuel, éventuellement intermédiaire ; les tableaux utilisent la réponse
complète validée. Le terminal SSE `output: []` peut être reconstruit à partir
des items complets ; `null` ou un champ absent restent refusés, même si le
connecteur natif tolère aussi ces variantes. Les réponses tardives ou invalides
ne sont jamais réparées pour pouvoir lancer une action.

Validation CPU : **417 tests de scène et 7 sous-tests**, dont **85 tests de la
boucle directe**. Revue indépendante en lecture seule des gardes de tour,
de l’historique et de la durée de vie des processus. Ces résultats ne ferment
pas les qualifications longues de T11 ni les limites motrices de T07.
