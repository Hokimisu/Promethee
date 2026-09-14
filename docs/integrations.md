# Intégrations à évaluer

État de cadrage : 15 septembre 2026. Ces sources établissent des capacités des projets tiers ; elles ne prouvent pas leur intégration à Promethee. L'accès aux modèles, les performances locales et les conversions de squelette restent à tester.

| Composant | Choix de départ | Statut dans Promethee |
|---|---|---|
| Raisonnement | Astra via l'API Responses | Non connecté |
| Agent persistant | Hermes Agent, réutilisé en amont | Non connecté |
| Voix | GPT-Live avec délégation vers l'agent | Non connecté |
| Mouvement | ARDY préentraîné, piloté par texte et contraintes | Non installé |
| Contrôle physique éventuel | GPC / ProtoMotions ou contrôleur adapté | À évaluer après le premier essai |
| Rendu | Moteur choisi après essai du squelette et de la latence | À décider |
| Notes | Markdown consultable dans Obsidian | Export local livré |

## Astra et voix

Astra supporte les entrées texte/image et les sorties texte ; sa fiche ne déclare pas de support audio. Le guide des agents vocaux décrit GPT-Live avec un backend séparé, ainsi qu'une chaîne transcription, agent et synthèse. Le raccord à Hermes exigera un adaptateur qui transmet contexte, résultats et interruptions.

- [Fiche Astra](https://developers.openai.com/api/docs/models/gpt-6-astra)
- [Architectures vocales](https://developers.openai.com/api/docs/guides/voice-agents)

Ne pas déduire l'accès API de la présence du modèle dans ChatGPT ou Codex. Ne pas ajouter de clé factice ni d'option d'environnement non consommée dans le socle. La configuration des fournisseurs sera introduite avec leur code d'intégration.

## Hermes

Hermes fournit mémoire, sessions, outils et compétences. Promethee lui exposera un ensemble réduit d'actions du monde avec des résultats vérifiables. Le moteur d'affichage et le corps devront continuer de fonctionner pendant ses appels de raisonnement.

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

Une séquence de poses ne prouve pas une prise, un appui ou une collision physique correcte. Avant de choisir le moteur de rendu : charger un checkpoint disponible, vérifier sa licence, adapter un squelette, réaliser une marche dirigée et une assise avec cibles explicites, puis observer les contacts et interruptions. Les politiques ProtoMotions ne sont pas interchangeables librement entre simulateurs ; lire leur fiche de modèle.

## Assets et redistribution

Le catalogue initial ne contient que des capacités logiques. Aucun fichier de modèle, rig, texture, voix ou capture de mouvement n'est livré. Pour tout ajout ultérieur, enregistrer sa source, sa licence, sa version et ses conventions d'unités/axes. La licence MIT de Promethee ne remplace pas les licences tierces.
