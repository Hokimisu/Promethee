# Expérience visée

Promethee explore un personnage virtuel persistant, capable de converser, de choisir une activité, de manipuler les objets de sa pièce et de reprendre ses projets au fil des sessions.

Le nom du projet, le modèle de raisonnement et l'identité du personnage sont distincts. La personnalité de l'avatar sera configurable ; elle ne doit pas dépendre du nom d'un fournisseur de modèles.

## Scénario de référence

1. L'avatar décide de préparer une petite présentation.
2. Il fait apparaître une pancarte, choisit un texte et la place dans la pièce.
3. L'utilisateur l'interrompt pour parler d'autre chose.
4. L'avatar suspend l'activité et répond ; son corps reste réactif.
5. Après la conversation ou lors d'une session suivante, il peut reprendre la présentation.
6. Son journal conserve les faits réalisés et le projet restant à terminer.

Le socle actuel reproduit uniquement une séquence logique écrite à l'avance. Le choix spontané de l'activité, la conversation et la réalisation 3D constituent les prochains jalons.

## Objets

| Objet | Usage souhaité | Travail nécessaire |
|---|---|---|
| Chaise | S'asseoir, se relever, déplacer | Assise, approche, contacts, transitions |
| Pancarte | Écrire, montrer, ranger | Surface de texte, orientation, prise |
| Doudou | Porter, poser, retrouver | Prise et attache ; déformation facultative plus tard |
| Lit | S'allonger et se relever | Surface de repos et mouvements adaptés |
| TV | Présenter ou regarder un contenu | Écran, lecture média, contrôles |

Au départ, les objets viennent d'un catalogue préparé. Faire apparaître un asset disponible et générer un nouvel objet 3D sont deux capacités distinctes. La génération d'assets n'est pas une condition de la première version.

## Autonomie

L'avatar pourra choisir des activités à partir de ses projets, de préférences mémorisées et de nouveaux événements. Les changements d'objectif restent observables et peuvent être interrompus par l'utilisateur. Une activité possède un début, un résultat et une raison de s'arrêter.

Le corps et le monde continuent de fonctionner entre les décisions. Le modèle de raisonnement est sollicité à l'arrivée d'événements pertinents, et éventuellement à intervalles espacés pour l'initiative ; il ne doit pas être appelé à chaque image.

L'autonomie dans la scène et l'accès aux services externes ont des périmètres explicites. Les objets ne donnent pas implicitement accès aux fichiers, aux comptes ou au réseau de l'utilisateur.

## Mémoire et évolution

La continuité doit être vérifiable : reprendre une activité, retrouver un objet, appliquer une correction ou réutiliser une compétence. La mise à jour de notes et de compétences ne constitue pas un réentraînement des poids du modèle.

La conscience ou l'expérience subjective ne sont pas des résultats revendiqués par ce projet. Le travail porte sur des comportements observables : initiative, mémoire, adaptation et cohérence entre paroles et actions. Des états tels que « repos » peuvent servir à organiser le comportement sans être présentés comme une preuve de sensations vécues.

## Qualité attendue

- Une seule identité et une activité commune à la voix, au corps et à la mémoire.
- Aucune réussite annoncée à partir d'un simple envoi de commande.
- Des mouvements qui peuvent être interrompus et ajustés au contexte.
- Des souvenirs dont on peut retrouver la provenance et corriger le contenu.
- Une interface sobre : un titre par bloc, des contrôles concrets, aucun texte décoratif.

