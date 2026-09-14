# Expérience visée

Promethee explore un personnage virtuel persistant, capable de percevoir son environnement, de converser, de se mouvoir, d'agir sur son espace et de conserver une mémoire au fil des sessions. L'usage de ces capacités reste ouvert.

Le nom du projet, le modèle de raisonnement et l'identité du personnage sont distincts. La personnalité de l'avatar sera configurable ; elle ne doit pas dépendre du nom d'un fournisseur de modèles.

## Cadre ouvert

Le projet définit des capacités et des contraintes d'exécution. Il ne prescrit aucune histoire à jouer, routine quotidienne, préférence pour un objet ou activité à accomplir. Les exemples servent à comprendre une possibilité et restent remplaçables.

Observer, attendre, explorer, changer d'avis, poursuivre ou abandonner une activité sont des possibilités. Leur pertinence dépend du contexte ; aucune ne constitue à elle seule un signe de réussite du projet. Une reprise doit être possible sans devenir obligatoire.

La démonstration actuelle est une fixture de vérification technique, écrite à l'avance. Son contenu ne doit servir ni de comportement par défaut, ni d'exemple à imiter dans les prompts, ni de souvenir initial, ni de cible de récompense. Elle vérifie la persistance et la reprise du runtime ; elle n'évalue pas l'autonomie.

## Exemples d'objets

Les objets évoqués ci-dessous illustrent différentes capacités à rendre disponibles. Ils ne fixent ni l'aménagement final, ni les goûts du personnage, ni l'ordre de développement.

| Objet | Usage souhaité | Travail nécessaire |
|---|---|---|
| Chaise | S'asseoir, se relever, déplacer | Assise, approche, contacts, transitions |
| Pancarte | Écrire, montrer, ranger | Surface de texte, orientation, prise |
| Doudou | Porter, poser, retrouver | Prise et attache ; déformation facultative plus tard |
| Lit | S'allonger et se relever | Surface de repos et mouvements adaptés |
| TV | Présenter ou regarder un contenu | Écran, lecture média, contrôles |

Au départ, les objets viennent d'un catalogue préparé. Faire apparaître un asset disponible et générer un nouvel objet 3D sont deux capacités distinctes. La génération d'assets n'est pas une condition de la première version.

## Autonomie

L'avatar pourra former et réviser des intentions à partir du contexte, de sa mémoire et de nouveaux événements. Il pourra aussi rester sans objectif actif. Le runtime conserve les décisions et leurs effets sans imposer de productivité, de fréquence d'action ou de mise en scène destinée à plaire à l'utilisateur. Les actions en cours restent interruptibles.

Le corps et le monde continuent de fonctionner entre les décisions. Le modèle de raisonnement est sollicité à l'arrivée d'événements pertinents, et éventuellement à intervalles espacés pour l'initiative ; il ne doit pas être appelé à chaque image.

L'autonomie dans la scène et l'accès aux services externes ont des périmètres explicites. Les objets ne donnent pas implicitement accès aux fichiers, aux comptes ou au réseau de l'utilisateur.

## Mémoire et évolution

La continuité doit être vérifiable : reprendre une activité, retrouver un objet, appliquer une correction ou réutiliser une compétence. La mise à jour de notes et de compétences ne constitue pas un réentraînement des poids du modèle.

La conscience ou l'expérience subjective ne sont pas des résultats revendiqués par ce projet. Le travail porte sur des comportements observables : initiative, mémoire, adaptation et cohérence entre paroles et actions. Des états tels que « repos » peuvent servir à organiser le comportement sans être présentés comme une preuve de sensations vécues.

## Qualité attendue

- Un contexte cohérent partagé par la voix, le corps et la mémoire, avec ou sans activité en cours.
- Aucune réussite annoncée à partir d'un simple envoi de commande.
- Des mouvements qui peuvent être interrompus et ajustés au contexte.
- Des souvenirs dont on peut retrouver la provenance et corriger le contenu.
- Des évaluations sur des situations variées, y compris sans consigne, sans objet familier et sans activité à reprendre. Aucun scénario unique ne définit le comportement attendu.
- Une interface sobre : un titre par bloc, des contrôles concrets, aucun texte décoratif.
