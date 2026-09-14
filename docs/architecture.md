# Architecture

## Socle présent

Un paquet Python sans dépendance d'exécution, une base SQLite locale et une interface en ligne de commande. Le scénario est déterministe. Il ne simule ni gravité, ni collision, ni mouvement continu. Ses transitions sont instantanées et servent à vérifier le contrat de persistance avant de connecter des modèles et un moteur graphique.

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

ARDY est un candidat pour la génération de mouvements à partir de texte et de contraintes. Il faudra adapter le squelette, les unités, les axes, les cadences et les points de contact. Les lèvres et le visage demanderont une animation dédiée.

L'autorité du snapshot actuel doit évoluer lorsque le contrôleur arrive : une commande acceptée n'est plus une transition instantanément réussie. Ajouter alors un cycle `accepted → running → completed / failed / cancelled`, corrélé à une intention et à la version du monde. Ne pas présenter le booléen `ok` du prototype comme l'accusé de réalisation d'une action 3D.

Les tickets T03–T05 du [plan d'implémentation](implementation-plan.md) précisent cette évolution, les rejets, l'état `interrupted` après perte de confirmation, les migrations et la compatibilité avec le socle logique.

## Voix et agent

La piste principale est GPT-Live avec délégation vers un adaptateur Hermes/Astra. Elle conserve un agent persistant tout en permettant la conversation vocale. Une chaîne transcription → agent → synthèse reste une option de diagnostic si nécessaire. Les capacités et l'accès effectif aux modèles doivent être vérifiés avant l'intégration payante.

Les événements d'interruption doivent parvenir à la conversation et au corps. Si l'avatar est assis, interrompre une réponse vocale ne doit pas le téléporter debout. L'annulation d'une action physique doit aboutir à une posture valide, puis être attestée par le contrôleur.

## Décisions initiales

- **Un processus local pour le socle.** Aucun bus de messages, conteneur, service réseau ou système de plugins n'est nécessaire à ce jalon.
- **SQLite pour l'état et les résultats ; Markdown pour les notes.** Les exports sont dérivés et ne remplacent pas la base.
- **Pas de fork de Hermes ni de modèles NVIDIA vendoriés.** Intégrer leurs interfaces au moment du besoin ; fixer les révisions validées à ce moment-là.
- **Moteur graphique à sélectionner par un essai de mouvement.** Valider import du squelette, contraintes spatiales, animation et GPU avant de figer Unity, Unreal ou une autre solution.
- **Aucun entraînement RL dans ce dépôt initial.** Commencer par vérifier ce que les modèles préentraînés permettent. Introduire un contrôleur physique ou un entraînement ciblé si les interactions demandées le justifient.

## Limites du socle

Les positions sont sur un plan de sol de 10 × 10 mètres. La portée d'un mètre est une règle logique arbitraire pour les tests, pas une mesure anatomique. Il n'y a pas de serveur, de rendu, d'agent externe, de synchronisation vocale ou de migration automatique des données. Les bases ayant une version de monde inconnue sont refusées.

Une activité échouée conserve son erreur et son curseur ; elle n'est pas relancée automatiquement. La replanification après changement du monde sera une responsabilité de l'adaptateur agent.
