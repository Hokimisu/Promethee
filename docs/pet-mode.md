# La boîte à Ariane

Orientation demandée par l'utilisateur le 16 septembre 2026. Une première
implémentation locale des quatre tranches est disponible dans la scène vocale
avec `mode: "pet"`. La qualification durable et les capacités motrices restent
distinctes de la livraison du code. Voir [le guide jouable](pet-environment.md).

## Expérience

On ouvre la boîte pour observer Ariane. Elle peut choisir une occupation,
continuer une idée précédente, changer d'avis, jouer avec ce qui est présent
ou rester tranquille. L'utilisateur intervient quand il le souhaite : parole,
apparition d'un objet, déplacement d'un objet ou du personnage, puis lancer.
Ces interventions modifient la situation ; elles ne dictent pas sa réaction.

Sa personnalité reste celle définie dans [son identité](characters/ariane.md) :
malicieuse, intellectuelle, sûre d'elle et mordante, avec une humeur changeante.
Les expériences peuvent former des goûts, des habitudes ou des projets.
Ni un emploi du temps quotidien ni une liste de gags ne sont préchargés.
Un personnage drôle n'exige pas une réplique à chaque événement.

« S'inventer une vie » autorise l'imagination du personnage : idées,
interprétations, histoires et intentions. La mémoire distingue ces créations
des événements vécus dans la boîte. Une histoire racontée ne déplace pas un
objet et ne prouve pas qu'une action a été exécutée.

## Rythme et continuité

Hermes reste l'unique agent qui décide. Un appel observe les événements utiles,
retrouve les intentions ou notes pertinentes, puis choisit de continuer,
changer d'activité, parler ou rester silencieux. La durée des appels ne pilote
pas la fréquence d'affichage. Le corps et les objets continuent de fonctionner
entre les décisions ; les mouvements peuvent être préparés à l'avance.

L'interface principale devient la scène avec une petite palette d'objets,
une entrée de dialogue et une pause. Le formulaire d'essai de 60 secondes et
les réglages de qualification restent des outils de développement séparés.
Pas de scénario à renseigner avant de regarder Ariane vivre.

Le mode d'exécution hors présence de l'utilisateur reste à préciser.
Hypothèse de départ pour l'implémentation : l'initiative avance pendant que
la boîte est ouverte, puis se suspend quand le dernier spectateur la ferme.
L'état et la mémoire persistent ; le temps fermé n'est pas rempli par des
souvenirs inventés. Le fonctionnement continu en arrière-plan reste une option
distincte à configurer. Cette hypothèse n'active aucun service ni budget actuel.

## Ce qu'on réutilise

| Élément | État au moment de cette orientation |
| --- | --- |
| Hermes résident, historique et observations du monde | Présents dans la scène vocale |
| Réveils sur événements, cadence, budget et pause | Implémentés ; essais courts, pas une vie autonome durable qualifiée |
| Mémoire sourcée en Markdown | Coffre lié au monde personnel en mode pet ; qualifications séparées |
| ARDY et personnage VRM | Présents ; déplacements et naturalité restent limités |
| VoxCPM2 et lèvres liées au son | Présents ; la faible latence n'est plus un prérequis produit |
| Prise et dépôt cinématiques de certains objets | Raccordés au même contrôleur en mode pet, à portée des bras ; ramassage au sol non pris en charge |
| Décor de la scène vocale | Visuel ; ne pas le présenter comme interactif |
| Déplacement direct par souris et lancers | Implémentés : saisie avec arrêt et réconciliation ; balle avec gravité et collisions simplifiées |

## Ordre de réalisation

La première tranche jouable réunit B01 et B02 : une continuité personnelle
avec des objets disponibles dans le même monde visible. Une boucle autonome
dans un décor vide ne suffit pas à livrer cette expérience. B03 ajoute ensuite
la manipulation directe du personnage, puis B04 les lancers.

### B01 — Une vie qui garde son contexte

Raccorder le même Hermes, l'initiative et la mémoire à un monde personnel neuf,
distinct des qualifications. Conserver les intentions décidées par Ariane et
leur état sans créer une seconde mémoire ou un second cerveau. Réutiliser les
notes de proposition de T10 et les activités existantes lorsque leurs contrats
conviennent ; ajouter un état seulement pour un besoin manquant identifié.

Un événement significatif, la fin d'une activité ou un réveil espacé peut
déclencher une décision. Regrouper ce qui arrive pendant un appel. Conserver
pause, budget visible, priorité des interventions et droit au silence.
La voix est disponible quand elle choisit de parler, pas à chaque décision.
Ne pas donner au personnage le dépôt, les tests ou les transcriptions de
qualification comme passé personnel.

**Vérifier :** continuité après reprise, absence de second agent et de répétition
automatique d'une commande, silence possible, pause, budget épuisé et changement
de contexte pendant une décision. Observer plusieurs sessions prolongées avec
dispositions et sollicitations variées. Le nombre d'actions ou de paroles n'est
pas le critère de réussite. Examiner les répétitions insensibles au contexte.

### B02 — Ajouter des objets dans sa boîte

Relier les instances visibles à leurs identifiants persistants et aux capacités
réellement disponibles. La palette utilise un petit catalogue préparé ; le
choix d'un objet n'impose pas son usage. Le raccord doit permettre au modèle
d'en percevoir la présence et, pour les interactions déjà qualifiées, d'agir
dessus. Ne pas activer simultanément un second pilote ARDY.

Une apparition ou un déplacement par l'utilisateur est enregistré comme une
intervention extérieure. Un simple objet décoratif n'annonce ni prise ni
collision physique. Transport pendant la présence et interruptions doivent
être vérifiés avant d'exposer ces capacités dans cette scène.

**Vérifier :** objets absents, déplacés ou tenus, identifiants stables, portée,
annulation et restauration. Le monde, l'image et le contexte Hermes doivent
décrire la même situation. Aucun objet n'apparaît pour forcer une routine.

### B03 — Déplacer Ariane et les objets à la souris

Le glisser-déposer est une intervention de l'utilisateur, pas une marche
accomplie par Ariane. Au début d'une saisie, arrêter la trajectoire concernée
et invalider son futur préparé ; attendre la confirmation avant la remise
en place. Le contrôleur réconcilie la pose déposée et publie l'événement.
Un retour tardif ne doit pas remettre l'avatar à son ancienne position.

La prévisualisation sous la souris reste distincte de la position confirmée.
Valider les limites de l'espace et les relations d'attachement avant d'enregistrer
le dépôt. Transmettre l'événement à Hermes avec son auteur ; laisser Ariane
choisir sa réaction. Aucun dialogue prédéfini ni demande de permission à Ariane
n'est nécessaire pour ce mécanisme de jeu demandé par l'utilisateur.

**Vérifier :** saisie pendant un geste, objet tenu, annulation de la saisie,
perte de connexion, deux onglets et ancien retour moteur. Une même intervention
rejouée ne se répète pas. La pause de l'initiative reste respectée.

### B04 — Lancer des objets

Ajouter une trajectoire, de la gravité et des collisions cohérentes pour les
objets lançables. Le résultat vient de la simulation, pas d'un prompt ou d'une
animation qui annonce un impact inexistant. Les collisions répétées sont
regroupées pour ne pas lancer un appel Hermes à chaque image.

**Vérifier :** lancer sans contact, contact et immobilisation, vitesses bornées,
interruption, persistance après arrêt et cohérence du récit avec les événements.
Le comportement drôle éventuel vient de l'improvisation du personnage, pas
d'une réaction imposée à chaque type de collision.

## Travail différé

GPT-Live, le remplacement du TTS, la réduction systématique des millisecondes,
les nouvelles voix et l'entraînement RL ne conditionnent pas B01–B03. La qualité
du rendu compte toujours, mais les décisions n'ont pas à suivre le rythme d'une
conversation humaine instantanée. Les capacités et défauts existants restent
documentés ; cette nouvelle priorité ne ferme pas artificiellement T07, T11 ou T12.
