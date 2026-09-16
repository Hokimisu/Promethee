# Répliques courtes, personnage et contrôle vocal

Qualification locale du 16 septembre 2026, dans le périmètre de T11.
Le serveur expérimental est `.local/realtime-voice-01/serve.py`, à
`http://127.0.0.1:2392/`. Il n'est pas encore la commande vocale publique du paquet.

## Configuration du jeu

Le personnage demandé par l'utilisateur est conservé dans
[Ariane](../characters/ariane.md), chargé par `dialogue.py` au démarrage de la
session, puis transmis par le paramètre natif `system_message`. Il ne
provient pas d'une fixture : malice, assurance, condescendance et goût des piques
restent reconnaissables lorsque son humeur change. Aucun souvenir de démonstration
n'est ajouté et aucun contexte de retour du travail n'est prérempli.

Le JSON contient toujours `text` et `delivery`. Le prompt vise 8 à 18 mots, en
une ou deux phrases ; la validation refuse plus de 24 mots, 280 caractères de
texte, 160 caractères de direction ou plusieurs balises par réplique. Les
apostrophes et mots composés restent un seul mot. Une sortie invalide échoue
explicitement, sans tronquer arbitrairement le sens ni vocaliser le JSON brut.

Le texte suivant est préparé pendant la lecture de la réplique actuelle, avec
une seule réplique en attente. Le budget de l'essai est de 12 appels maximum
sur 60 secondes. Une intervention invalide immédiatement les réponses obsolètes.
La gestuelle de présence ARDY continue indépendamment de cette préparation.

## Contrôles VoxCPM2 raccordés

`speech_text.py` est partagé entre le serveur et le worker Vox. Il conserve
accents, apostrophes et ponctuation. Les balises documentées sont envoyées au
modèle avec leur casse exacte, mais retirées des sous-titres. Les directions
parenthétiques sont nettoyées puis assemblées dans un unique préfixe ; les
didascalies dans le texte, balises inconnues et SSML sont refusés par la chaîne
de dialogue. Aucun silence d'une durée exacte n'est promis.

La référence approuvée, le clonage en mode référence seule, CFG 2 et les 10 pas
de synthèse restent inchangés. La prise en compte des directions est une
capacité probabiliste : leur transmission ne prouve pas la qualité du jeu.

Sources officielles : [style](https://voxcpm.readthedocs.io/en/latest/models/voxcpm2.html#style-control),
[balises](https://voxcpm.readthedocs.io/en/latest/cookbook.html#extra-spice-non-verbal-tags),
[ponctuation](https://voxcpm.readthedocs.io/en/latest/usage_guide.html#punctuation-and-pauses).
Voir également [la recherche détaillée](10-voxcpm-prompting.md).

## Comparatif natif Luna / Astra

Deux demandes identiques par modèle, historiques séparés, effort `low`, même
profil Hermes limité aux cinq outils Promethee, aucun appel d'outil, aucun
fallback. Résultats dans `.local/realtime-voice-01/luna-qualification/run-01/`.

**Correction de périmètre après audit :** ce comparatif a chargé les sources
Hermes `C:/Users/Cat6A/AppData/Local/hermes/hermes-agent` (`cd297653…`), alors
que le serveur utilise `G:/Projects/Promethee/.local/hermes-agent` (`2179a279…`).
L'interpréteur est celui de C: dans les deux cas. Ces comparaisons restent des
appels réels, mais ne mesurent pas un gain dans la simulation. L'essai navigateur
ci-dessous utilise bien les sources G:. Les prochaines comparaisons doivent
enregistrer les chemins `__file__` effectifs, en plus des modèles et versions.

| Mesure | Luna | Astra |
| --- | --- | --- |
| Temps total du premier tour | 14,50 s | 13,84 s |
| Temps total du second tour | 12,96 s | 13,60 s |
| Appel de conversation, premier tour | 4,75 s | 5,40 s |
| Appel de conversation, second tour | 4,73 s | 5,16 s |
| Nombre de mots | 13 / 10 | 18 / 12 |

Les quatre réponses sont du JSON valide et la seconde rappelle correctement
le message précédent. Ce petit échantillon ne démontre pas un gain global de
Luna : son premier tour a payé un import plus long. Authentification, imports
et construction Hermes ajoutent encore environ huit secondes à chaque tour.
`low` était déjà actif avec Astra ; il n'a pas été abaissé une seconde fois.

L'option locale `--model gpt-5.6-luna`, désormais utilisée par défaut dans cet
essai, permet de qualifier le dialogue avec Luna.
Il s'agit d'un remplacement du modèle de ce même contexte Hermes, pas d'un
second cerveau doté d'une mémoire indépendante.

## Essai dans le navigateur

Artefacts : `.local/realtime-voice-01/dialogue-trial-4d843737/`. Quatre répliques
improvisées, de 12 à 15 mots, avec les directions transmises au moteur. Un rire
puis un soupir sont sollicités uniquement par les interventions de qualification,
pas par une routine du personnage. Leur balise ne figure pas dans les sous-titres.

Les sorties durent 4,96 s, 4,80 s, 6,24 s et 4,48 s. Le navigateur a confirmé
trois lectures complètes et une quatrième interrompue à la limite de 60 s,
soit 19,62 s réellement lues, sans manque de PCM. 354 poses distinctes ont été
observées ; la bouche variait avec le PCM joué (poids 0,59 lors d'une mesure).
Aucune erreur corporelle ou vocale n'a été signalée. Cela vérifie le chemin
technique, pas la qualité subjective du rire, du soupir ou de l'identité vocale.

Après cet essai, l'utilisateur a explicitement jugé le son « parfait » et
identifié la latence comme le problème restant. Cette validation porte sur la
configuration vocale courante, pas sur un modèle réentraîné : conserver sa
référence, ses réglages et son prompting pendant les optimisations Hermes.

Dans cette référence avant préchauffage, le temps jusqu'au texte était de
18,16 s au premier tour, puis 15,27 s,
15,30 s et 15,67 s. Les phrases plus courtes exposent donc les temps morts :
elles ne rendent pas à elles seules la conversation instantanée. La prochaine
optimisation utile était le préchauffage du worker natif, avec les mêmes garanties
de profil, historique et annulation ; sa qualification est décrite ci-dessous.

Validation : 71 tests locaux et 7 sous-tests ; socle 553 tests réussis,
2 ignorés ; Ruff et construction du paquet réussis. Une session neuve est
ouverte après la qualification pour ne pas réinjecter ces scènes dans l'essai
suivant.

## Préchauffage Hermes qualifié

Le worker peut désormais être préparé avant l'intervention (`--prewarm`,
opt-in dans le socle, activé dans cet essai). Il ne lance aucun appel modèle
avant l'activation. Le futur tour reste inactif et privé ; l'historique est lu
au moment du message, et l'authentification ainsi que le profil sont revérifiés.
Une interruption invalide le tour actif ; la fermeture détruit aussi le worker
en réserve. Son expiration et les courses d'activation ont des tests dédiés.

La personnalité et le contrat vocal approuvés sont maintenant transmis par
`system_message`, sans recopier leurs 2 852 caractères dans chaque message
utilisateur. Leur texte et les réglages Vox n'ont pas changé.

Une paire de vrais appels, mêmes sources G: `2179a279…`, donne **4,53 s**
après message lorsque le worker est prêt, contre **15,43 s** à froid. La
préparation préalable prend 9,09 s. L'appel de conversation varie lui-même
de 4,10 à 7,22 s : cette différence ne peut pas être attribuée au préchauffage.
Provenance et mesures :
`.local/realtime-voice-01/luna-qualification/run-prewarm-g-01/`.

L'essai navigateur de 60 s est enregistré dans
`.local/realtime-voice-01/dialogue-trial-7919463e/`. Il utilise le corps et la
voix actifs, avec un contexte de qualification neuf, sans intervention injectée.

| Tour | Message → texte validé | Appel de conversation | Observation |
| --- | --- | --- | --- |
| 1 | 3,81 s | 3,34 s | Worker prêt avant le message |
| 2 | 14,37 s | 3,82 s | Préparation encore en cours lors du message |
| 3 | 3,50 s | 2,90 s | Worker déjà prêt |
| 4 | 26,35 s | 21,36 s | Préparation partielle puis appel de conversation lent |
| 5 | 4,07 s | 3,58 s | Worker déjà prêt |
| 6 | 8,81 s | 4,80 s | Préparation partielle ; limite de 60 s avant lecture |

Le navigateur confirme cinq lectures complètes, soit **23,84 s de voix**,
sans sous-alimentation PCM ; la sixième réponse n'est pas lue. 504 poses
distinctes sont observées, sans erreur du corps ou de la voix. Aucun des six
tours n'a appelé d'outil. Les instructions système ne figurent dans aucun
message utilisateur persisté. La lenteur du quatrième appel n'est donc pas
une boucle d'outils ; ce relevé ne sépare pas encore réseau, fournisseur et
génération interne.

**Le dialogue n'est pas encore fluide.** Un seul worker jetable ne masque pas
toute sa préparation lorsque les répliques sont brèves. Les réponses dont le
worker était prêt montrent un gain, mais cet essai ne démontre ni un délai
garanti ni un débit continu. La suite prioritaire est une instance Hermes
résidente avec rattachement explicite des outils au tour courant, puis une
mesure du premier texte reçu via les callbacks natifs.

Validation après intégration : **577 tests réussis, 2 ignorés**, dont 24 dédiés
au préchauffage ; tests locaux de dialogue/serveur 27 réussis et 7 sous-tests ;
Ruff et construction du paquet réussis. Le service est relancé avec une session
neuve après la qualification. Le contexte de test ne devient pas sa mémoire.

## Scène livrée avec Hermes résident

La [scène expérimentale](../../experiments/voice/realtime/README.md) est désormais
livrée avec sa configuration et ses environnements séparés. Le mode explicite
`resident: true` conserve Hermes entre les tours réussis ; le transport MCP
est fermé puis reconnecté avec l'autorité du nouveau tour. Le premier essai
natif de trois tours et les interfaces employées sont détaillés dans
[l'audit Hermes](12-hermes-lifecycle.md#mode-résident-livré-et-qualification-native).

L'essai `dialogue-trial-5d84d867`, réalisé le 16 septembre 2026, utilise les
sources livrées, un environnement vocal neuf Python 3.10.12, les 160 versions
épinglées, les poids VoxCPM2 et la référence approuvés inchangés. Hermes charge
la source `2179a279…`, avec Luna, effort `low`, même contrat système et mêmes
cinq outils. Le monde neuf est marqué `qualification`. Aucune suite CPU ne
tournait pendant cet essai. Le sujet du diplôme est une fixture ponctuelle,
absente de la mémoire personnelle et de la configuration initiale.

| Mesure | Observation de cette session |
|---|---:|
| Réponses Hermes terminées | 10, sans appel d'outil |
| Message → texte validé | 3,55 à 5,77 s |
| Boucle native par tour | 2,06 à 3,65 s |
| Reconnexion MCP après le premier tour | 1,86 à 1,96 s |
| Premier PCM après demande de synthèse | 94 à 308 ms |
| Audio généré | 55,20 s |
| Audio effectivement joué | 54,40 s |
| Reçus de lecture | 9 complets, dernier interrompu à la limite de 60 s |
| Sous-alimentations du lecteur PCM | 0 |
| Poses distinctes capturées | 503 |

La préparation du résident n'apparaît qu'au premier tour ; aucun contrat
système n'est répété dans les messages utilisateur conservés. La bouche est
pilotée par le PCM réellement lu : une observation navigateur pendant la
parole donne une amplitude de 0,298 et une ouverture de 0,879, puis fermeture
à l'arrêt. Ce contrôle ne qualifie ni la synchronisation phonétique ni toute
la naturalité corporelle. Les traces, WAV et reçus de lecture restent locaux
sous `.local/realtime-voice-01/dialogue-trial-5d84d867/` ; la session source est
`.local/realtime-publication-runs/session-6ebd5149b6b4/`.

Un premier essai publié, `dialogue-trial-177d70e0`, avait produit huit réponses
de 3,34 à 5,06 s, mais le navigateur avait arrêté la lecture après **12,88 s**
sur `Failed to fetch`. Il ne compte pas comme lecture de 60 s réussie. Le
serveur HTTP/1.0 ouvrait un nouveau socket à chaque requête ; il utilise
maintenant HTTP/1.1 avec connexions persistantes et expiration bornée. Un test
réseau réel sur CPU vérifie 200 lectures et une télémétrie sur une seule
connexion. La cause exacte de la première coupure n'est pas établie ; la
qualification suivante confirme l'absence de coupure de lecture sur son
parcours, sans garantir qu'aucune requête de télémétrie puisse expirer.

Le chevauchement entre prochaine décision, voix et corps masque maintenant
une grande partie du délai dans cet essai. **Cela ne constitue pas un A/B
isolé**, ni une réponse instantanée après intervention : la première phrase
attend encore le modèle, puis le prébuffer du lecteur. La connexion MCP coûte
toujours près de deux secondes par tour. Le coût monétaire et le cache
fournisseur ne sont pas déduits de ces durées.

Validation du code livré : 605 tests du socle réussis, 2 ignorés ; 124 tests
de la scène et 7 sous-tests réussis ; 16 tests du navigateur avec les médias
privés qualifiés (14 et 2 ignorés sans ces médias). Ruff, format et construction
du paquet et du rendu réussis. Le service est ensuite relancé dans un monde
neuf : la fixture n'est pas conservée comme conversation courante.

## Limites de parallélisation

La génération du prochain texte, la lecture audio et la présence corporelle
sont déjà concomitantes. Les actions explicites ont encore un problème séparé :
les observations de présence font évoluer la révision entre `read_world` et
`submit_action`. Leur synchronisation reste à traiter sans remplacer
silencieusement la révision du modèle ni geler le corps pendant sa réflexion.
Cette modification du dialogue ne résout pas ce conflit.

## Coût de Luna

Le [barème officiel consulté le 16 septembre 2026](https://learn.chatgpt.com/docs/pricing#token-rates)
donne, par million de tokens, 5 crédits en entrée, 0,5 en entrée mise en cache
et 30 en sortie pour Luna, contre 250 / 25 / 1 250 pour Astra. À nombres de
tokens identiques, Luna représente donc 50 fois moins de crédits d'entrée et
environ 41,7 fois moins de crédits de sortie. Ce rapport tarifaire n'est pas une
mesure de consommation de notre essai : le volume, le cache et le raisonnement
diffèrent. La connexion actuelle utilise Hermes avec l'authentification ChatGPT,
pas une clé API facturée séparément.
