# Ouvrir la boîte à Ariane

La scène vocale possède un mode `pet`, sans scénario initial ni durée de
60 secondes. Il conserve Hermes, sa mémoire sourcée et VoxCPM2. Les objets
affichés correspondent aux instances du monde ; le déplacement par souris
est attribué à l'utilisateur.

## Utilisation

1. Ouvrir la scène, puis **Ouvrir la boîte** pour autoriser le son.
2. **Reprendre** active la vie autonome avec le budget affiché. Une décision
   peut rester silencieuse. **Pause de vie** persiste après redémarrage.
   **+10 décisions** recharge le budget sans retirer la pause ni couper la parole.
3. Choisir **Balle** ou **Doudou**, puis cliquer au sol pour ajouter un objet.
   Le doudou peut aussi être présenté **En hauteur**, à portée des bras.
4. Faire glisser Ariane ou un objet. Le marqueur indique le dépôt proposé ;
   seul le retour du contrôleur confirme la nouvelle position.
5. Choisir **Lancer**, tirer une flèche depuis une balle et relâcher.
   Le bouton **Déplacer** revient à la manipulation ordinaire.
6. Écrire pour intervenir. Le microphone reste facultatif et désactivé au départ.

Les onglets visibles renouvellent un bail de 15 secondes. Quand le dernier
disparaît, les décisions, mouvements et lancers se suspendent. La mémoire,
le budget et les positions restent conservés. Aucune activité n'est inventée
pour combler une absence. Une reprise relit ce même monde et ce même coffre.

## Configuration locale

Partir de `experiments/voice/realtime/config.example.json` et conserver les
chemins explicites des modèles déjà préparés. Ajouter :

```json
{
  "mode": "pet",
  "world_dir": "chemin/monde-personnel",
  "vault": "chemin/coffre-personnel",
  "resident": true,
  "world_context": true,
  "initiative": {"budget": 24, "interval": 90}
}
```

Ce fragment complète le fichier existant. Les chemins relatifs partent du
dossier de configuration. Ne pas fournir `resume_world` : `world_dir` est créé
une fois puis repris. Un monde de qualification ne peut pas être promu en monde
personnel. Le coffre neuf est lié à cet identifiant de monde ; un coffre
existant doit déjà correspondre. Les paramètres d'initiative initiaux ne sont
appliqués qu'à la création, en pause. Une reprise ne recharge pas le budget.

Lancer le même `serve.py --config <fichier>`, après compilation du frontend et
coordination du GPU décrites dans le [guide de la scène](../experiments/voice/realtime/README.md).
Le cache de l'encodeur ARDY doit contenir les postures déjà qualifiées et la
présence vocale. Le repos pet emploie le prompt `standing` de ce catalogue.

## Contrat de manipulation

`POST /pet_watch` ouvre un spectateur. `POST /pet` reçoit
`{request_id, expected_command_revision, action:{kind,args}}`.
Le catalogue et sa géométrie arrivent dans `state.pet`.
`POST /initiative_budget` avec `{add_budget:10}` recharge explicitement le budget
persistant sans changer la pause, la session vocale ni son curseur de lecture.

| Intervention | Arguments |
| --- | --- |
| `spawn` | `model`, `position:[x,y,z]` |
| `grab_begin` | `target:"avatar"` ou `target:"object", object_id` |
| `grab_end` | `grab_id`, position `[x,z]` pour Ariane ou `[x,y,z]` pour un objet ; `velocity` facultative pour une balle |
| `grab_cancel` | `grab_id` |
| `relocate_avatar` | `position:[x,z]` |
| `relocate_object` | `object_id`, `position:[x,y,z]` |
| `throw` | `object_id`, `velocity:[vx,vy,vz]` |

Une saisie suit l'identité courante de la cible : les observations intermédiaires
ne la rendent pas périmée. Une seule saisie existe à la fois ; sa fin utilise
son identifiant, expire après 30 secondes et se libère au redémarrage.
Les mutations simples contrôlent la révision. Un rejeu identique n'interrompt
pas de nouveau la scène ; un identifiant réutilisé autrement est refusé.

Le propriétaire unique du corps invalide le mouvement et son futur préparé
avant d'appliquer une intervention. Une translation d'Ariane conserve les
rotations préparées et déplace aussi l'objet attaché à sa main. Les résultats
asynchrones périmés sont drainés. Une action interrompue n'est pas une marche
réussie. Les observations, événements et reçus d'intervention sont enregistrés
dans la même transaction SQLite. Les exports Markdown distinguent les
interventions extérieures des décisions d'Ariane et conservent les éditions
manuelles.

## Limites actuelles

- Le catalogue spatial utilisable contient une balle et un doudou. Les murs
  sont le décor de la boîte. Aucun meuble ne prétend offrir une action absente.
- Les prises utilisent les bras, sans déplacement automatique du tronc :
  un objet au sol n'est pas ramassable depuis une posture debout. La portée
  et les collisions sont contrôlées, les échecs restent visibles.
- Un objet tenu doit être posé avant sa manipulation séparée par la souris.
  Déplacer Ariane conserve son attachement.
- La prise et le dépôt sont stationnaires. La présence gestuelle générique
  et la locomotion restent suspendues pendant la tenue : le transport animé
  n'est pas encore qualifié dans cette scène. La parole reste disponible.
- Seules les balles ont une dynamique. Les doudous restent cinématiques.
  La balle rebondit contre le sol, les murs, une capsule debout représentant
  Ariane et des volumes simplifiés des autres objets. Le corps ne subit pas
  d'impulsion et les autres objets ne reçoivent pas d'élan.
- Pendant une saisie ou un lancer, les nouvelles actions corporelles sont
  temporairement refusées. La voix peut continuer. Ce choix évite de jouer
  une prise ou un déplacement préparé sur un objet dont la position a changé.
- La présence et les déplacements conservent les limites actuelles d'ARDY et
  de l'adaptation VRM. Un prototype manipulable ne démontre pas encore une
  animation humaine naturelle ni une vie autonome intéressante sur plusieurs jours.
  Si les gestes au repos sont interrompus après leurs tentatives bornées,
  **Pause de vie**, puis **Reprendre** permet de les retenter depuis la pose conservée.

Les essais CPU couvrent l'idempotence, les courses d'annulation, les deux
pointeurs, les reprises, la physique bornée et l'atomicité. Les essais interactifs
utilisent un monde et un coffre jetables distincts du monde personnel livré.
Le [rapport d'essai](research/19-pet-environment.md) consigne les résultats visibles
et les défauts rencontrés.
