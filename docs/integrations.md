# Intégrations à évaluer

État vérifié : 15 septembre 2026. Les sources tierces établissent des capacités
des projets amont ; les liens vers les qualifications Promethee précisent ce
qui a réellement été essayé localement.

| Composant | Choix de départ | Statut dans Promethee |
|---|---|---|
| Raisonnement | Astra, mode d'API explicite dans l'hôte | Accès OpenAI configuré : HTTP 401 ; aucune inférence Astra validée |
| Agent persistant | Hermes Agent 0.20.5, réutilisé en amont | Hôte texte, historique et outils vérifiés avec fournisseur local de test ; [qualification](hermes-setup.md) |
| Voix | GPT-Live reste la cible ; chaîne transcription/Hermes/synthèse pour le diagnostic | [Chaîne et interruptions](voice.md) vérifiées avec fournisseurs simulés ; pas d'accès audio réel qualifié |
| Mouvement | ARDY préentraîné, piloté par texte et contraintes | Génération et pilote cinématique réels ; déplacements encore peu fiables, [mesures](motion-validation.md) |
| Contrôle physique éventuel | GPC / ProtoMotions ou contrôleur adapté | À évaluer après le premier essai |
| Rendu | Viser pour le monde ; Three.js/VRM pour l'apparence | [Monde et squelette](rendering.md), [avatar animé en lecture seule](avatar-rendering.md) ; interactions corporelles non livrées |
| Notes | Markdown consultable dans Obsidian | Sources, recherche et corrections raccordées à Hermes ; [contrat et tests](memory.md) |

## Astra et voix

Astra supporte les entrées texte/image et les sorties texte ; sa fiche ne déclare pas de support audio. Le guide des agents vocaux décrit GPT-Live avec un backend séparé, ainsi qu'une chaîne transcription, agent et synthèse. Le raccord à Hermes exigera un adaptateur qui transmet contexte, résultats et interruptions.

- [Fiche Astra](https://developers.openai.com/api/docs/models/gpt-6-astra)
- [Architectures vocales](https://developers.openai.com/api/docs/guides/voice-agents)

Ne pas déduire l'accès API de la présence du modèle dans ChatGPT ou Codex. La
commande `chat` utilise désormais `PROMETHEE_OPENAI_API_KEY`, un modèle et un mode
d'API explicites ; elle ne choisit aucun fournisseur de secours. Le compte n'a
pas encore permis de qualifier cette intégration réelle. GPT-Live reste à
raccorder ; la chaîne transcription → Hermes → synthèse dispose d'un diagnostic
exécutable, encore sans mesures de fournisseur ou de périphérique réels.

## Hermes

Hermes fournit mémoire, sessions, outils et compétences. Promethee expose cinq
outils du monde et quatre outils mémoire optionnels, avec un historique natif
persistant. Son profil désactive le contexte et la mémoire globale de Hermes.
Le corps et l'affichage restent séparés des processus de conversation.

- [Dépôt officiel](https://github.com/NousResearch/hermes-agent)
- [Mémoire](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory)

## ARDY et contrôle moteur

ARDY publie du code, des checkpoints et des démos de génération interactive, contrôlée par texte et contraintes cinématiques. Son dépôt documente principalement des essais sous Ubuntu avec un GPU NVIDIA. La compatibilité avec la machine cible doit être mesurée, pas supposée.

- [Projet ARDY](https://research.nvidia.com/labs/sil/projects/ardy/)
- [Code et installation](https://github.com/nv-tlabs/ardy)
- [Modèles publiés](https://huggingface.co/collections/nvidia/ardy)
- [GPC : préentraînement et adaptation de contrôleurs](https://yi-shi94.github.io/gpc-page/)
- [Modèles préentraînés ProtoMotions](https://nvlabs.github.io/ProtoMotions/getting_started/pretrained_models.html)
- [MotionBricks : capacités et état de publication](https://nvlabs.github.io/motionbricks/)

Une séquence de poses ne prouve pas une prise, un appui ou une collision physique
correcte. Les essais ARDY ont permis de retenir Core et Viser, puis de mesurer
déplacements, postures et interruptions. Les appuis restent insuffisants et
l'assise ciblée n'est pas livrée. Les politiques ProtoMotions ne sont pas
interchangeables librement entre simulateurs ; lire leur fiche de modèle.

## Assets et redistribution

Le catalogue d'objets reste logique. L'avatar VRM pixiv est téléchargé localement
à une révision et une empreinte vérifiées ; sa [fiche de provenance](assets/pixiv-vrm-sample.md)
précise sa licence. Les poids moteurs et les assets ne sont pas redistribués
dans Git. Pour tout ajout, enregistrer source, licence, version et conventions
d'unités/axes. La licence MIT de Promethee ne remplace pas les licences tierces.
