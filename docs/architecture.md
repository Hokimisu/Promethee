# Architecture

## Socle présent

Un paquet Python sans dépendance d'exécution obligatoire, une base SQLite locale et une interface en ligne de commande. Un visualiseur Viser optionnel lit ce monde et les mouvements ARDY enregistrés. Le scénario logique est déterministe. Il ne simule ni gravité, ni collision, ni mouvement continu. Ses transitions sont instantanées et servent à vérifier le contrat de persistance avant de connecter le contrôleur.

`world.py` valide les actions et leurs préconditions. `runtime.py` persiste un snapshot, les résultats des commandes et les plans d'activité. `journal.py` exporte les actions logiques réussies en Markdown. `demo.py` contient une fixture de sept actions ; ce fichier n'est pas un cerveau autonome.

Une transaction regroupe l'action, son événement et l'avancement de l'activité. Une panne entre ces écritures ne doit pas créer de divergence. Les commandes portent des identifiants stables afin qu'une retransmission n'effectue pas deux fois une action.

Le plan séquentiel est un mécanisme du socle pour exécuter des commandes et tester leur reprise. Il ne définit pas toute l'activité future de l'avatar : perception, conversation, exploration et absence d'objectif doivent pouvoir exister sans plan actif. La fixture `demo.py` et ses exports restent hors du contexte et de la mémoire du futur agent.

## Responsabilités cibles

| Composant | Responsabilité | N'est pas autorité sur |
|---|---|---|
| Agent Astra dans Hermes | Intentions, conversation de fond, choix d'activité | Résultat physique d'une action |
| Voix | Dialogue audio, interruptions, restitution des résultats | Seconde mémoire indépendante |
| Runtime du monde | Objets, positions, capacités, activité et résultats | Pensées ou sentiments supposés |
| Contrôle du corps | Réaliser les intentions et signaler l'état d'exécution | Création libre d'objets hors catalogue |
| Mémoire | Retenir et retrouver des expériences sourcées | Position actuelle d'un objet |

## Du langage au mouvement

Lorsqu'une intention implique un objet, le runtime résout sa cible par identifiant, vérifie ses capacités et transmet les contraintes géométriques au contrôleur moteur. Celui-ci adapte les poses et retourne des événements d'exécution. Les exemples de commandes ne doivent pas devenir des intentions automatiquement suggérées à l'agent.

ARDY Core produit désormais les poses du premier contrôleur cinématique. `ardy_worker.py` tourne dans son environnement Python 3.11 ; `motion_process.py` échange des messages JSON bornés et des fichiers numériques locaux avec le runtime CPU. `kinematic.py` lit les poses à 20 Hz et persiste des observations toutes les 250 ms. Les points de contact et la fiabilité des postures restent à qualifier ; les lèvres et le visage demanderont une animation dédiée.

`execution.py` fournit désormais un cycle `accepted → running → completed / failed / cancelled`, avec rejet avant envoi et état `interrupted` après perte de confirmation. Les retours du pilote mettent le monde à jour atomiquement avec le résultat et l'événement. Le contrôleur possède un bail exclusif et chaque retour est lié à sa session. Des tests CPU et un premier raccord ARDY réel vérifient ces opérations ; voir les [mesures et limites T07](motion-validation.md). Le booléen `ok` conserve uniquement son sens logique.

Les tickets T03–T05 du [plan d'implémentation](implementation-plan.md) précisent cette évolution, les rejets, l'état `interrupted` après perte de confirmation, les migrations et la compatibilité avec le socle logique.

Le mode optionnel [`--continuous-motion`](continuous-motion.md) génère et
prépare des blocs de 40 poses pendant la lecture du bloc engagé. Son contexte
distingue les poses observées du futur validé ; une annulation retire ce futur.
Il reste expérimental : le débit, les transitions et la marche ne sont pas
qualifiés pour une présence naturelle continue.

## Voix et agent

`chat.py` lance la boucle native Hermes avec un historique persistant et des
outils MCP limités au monde. Une correction invalide le tour précédent avant
la fermeture de ses processus. La boucle native Hermes utilise soit une clé
API explicite, soit sa connexion ChatGPT existante dans un profil dédié.
Astra a conversé, lu le monde, retrouvé le contexte après redémarrage, demandé
une posture réellement exécutée par ARDY et confirmé une annulation. Les
résultats récents du contrôleur sont accessibles avec la lecture du monde,
même quand l'ancien tour de raisonnement a été invalidé. L'accès à l'API par la clé configurée
avait répondu HTTP 401 ; il est distinct de ce raccord ChatGPT.

`memory.py` ajoute quatre outils lorsque l'hôte configure un coffre neuf lié
à une session interactive. SQLite conserve les sources et les liens de
correction ; la recherche lit les notes Markdown, y compris leurs éditions
manuelles. Les notes restent des données historiques : le monde courant fait
autorité et une recherche ne reprend aucune activité. Les jeux de qualification
et les anciennes sessions non classées sont exclus. Voir le [contrat mémoire](memory.md).

Le choix vocal actuel de l'utilisateur est VoxCPM2 local, avec Luna testé pour
les répliques du même contexte Hermes. La [scène expérimentale](../experiments/voice/realtime/README.md)
est livrée dans le dépôt, séparée du paquet, avec chemins et commande vocale
configurables. Elle qualifie la sortie vocale, ses directions et la présence
corporelle, sans microphone. Le [rapport de dialogue](research/11-short-dialogue.md) mesure
les délais et distingue ce qui est effectivement joué. Le préchauffage optionnel
du socle construit un worker avant le message, sans appel modèle ; son activation
reçoit l'historique frais. Le contrat vocal stable utilise `system_message`.
Le mode optionnel `--resident` conserve un seul agent Hermes entre les tours
réussis, mais reconnecte MCP à chaque nouveau tour autorisé. Les erreurs et
interruptions actives détruisent cette instance. L'historique et les résultats
restent détenus par le monde ; aucune seconde mémoire n'est ajoutée. Voir la
[qualification native et ses limites](research/12-hermes-lifecycle.md).

La piste GPT-Live reste un raccord distinct à qualifier avec un fournisseur
réel. `voice.py` fournit une chaîne de diagnostic transcription → même hôte
Hermes → synthèse, avec micro à la demande et génération invalidée lors d'une
correction. Ses clients audio ont été vérifiés contre un fournisseur simulé ;
périphériques réels et interruption acoustique restent à qualifier. Voir les
[commandes et limites](voice.md).

Les événements d'interruption doivent parvenir à la conversation et au corps. Si l'avatar est assis, interrompre une réponse vocale ne doit pas le téléporter debout. L'annulation d'une action physique doit aboutir à une posture valide, puis être attestée par le contrôleur.

## Décisions initiales

- **Un processus local pour le socle.** Aucun bus de messages, conteneur, service réseau ou système de plugins n'est nécessaire à ce jalon.
- **SQLite pour l'état et les résultats ; Markdown pour les notes.** Les exports sont dérivés et ne remplacent pas la base.
- **Pas de fork de Hermes ni de modèles NVIDIA vendoriés.** Intégrer leurs interfaces au moment du besoin ; fixer les révisions validées à ce moment-là.
- **ARDY Core et Viser retenus après l'essai T02.** Le rendu T06 reste en lecture seule ; voir la [décision et ses mesures](decisions/001-motion-stack.md).
- **Aucun entraînement RL dans ce dépôt initial.** Commencer par vérifier ce que les modèles préentraînés permettent. Introduire un contrôleur physique ou un entraînement ciblé si les interactions demandées le justifient.

## Limites du socle

Les positions sont sur un plan de sol de 10 × 10 mètres. La portée d'un mètre est une règle logique arbitraire pour les tests, pas une mesure anatomique. `viewer.py` reste en lecture seule ; `run.py` ajoute des boutons passant par le service d'exécution et son unique pilote. La conversation Astra et la synchronisation vocale restent à qualifier. Le schéma v8 conserve la pose articulée observée, les tours conversationnels, le registre de mémoire et la configuration d'initiative. Les migrations sont explicites, transactionnelles et précédées d'une sauvegarde vérifiée ; les versions inconnues sont refusées.

`initiative.py` réserve un budget dans la même transaction que l'ouverture d'un
tour du même Hermes. Les changements sont regroupés pendant une décision ;
la pause survit au redémarrage. Aucun réveil n'est actif sans configuration
explicite. Voir le [contrat et la qualification](initiative.md).

Une activité échouée conserve son erreur et son curseur ; elle n'est pas relancée automatiquement. La replanification après changement du monde sera une responsabilité de l'adaptateur agent.
