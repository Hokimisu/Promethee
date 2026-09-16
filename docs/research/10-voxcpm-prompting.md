# Prompting vocal VoxCPM2 pour Ariane

Recherche du 16 septembre 2026. Sources : documentation liée par le dépôt
OpenBMB, démonstration officielle et code installé `voxcpm==2.0.3`.
Poids locaux : `32279effe8c19989596f05d353d1447f51d9e915`.
Cette note distingue documentation, observation du code et propositions à écouter.
Aucune nouvelle voix ni modification du serveur actif n'est validée par cette recherche.

## Contrôles documentés

| Intention | Entrée | Portée et limite |
| --- | --- | --- |
| Ton, débit, intensité | Une description anglaise ou chinoise entre `()` avant la réplique | Direction générale ; pas une commande temporelle exacte. |
| Rire ou soupir | `[laughing]`, `[sigh]` dans le texte | Balises du cookbook, à employer avec parcimonie. |
| Hésitation ou interjection | `[Uhm]`, `[Shh]` | Événements vocaux ; ne représentent pas un silence mesuré. |
| Respiration du texte | Virgule, point, point d'interrogation, points de suspension | Indications prosodiques dont la durée varie. |

La référence fournit le timbre en mode `reference`; la description fournit le
style. Le mode avec transcription de référence vise la continuation fidèle et
la démonstration y désactive les instructions de style.
[Modes et style](https://voxcpm.readthedocs.io/en/latest/models/voxcpm2.html#style-control),
[démonstration officielle](https://github.com/OpenBMB/VoxCPM/blob/main/app.py).

Le cookbook répertorie aussi `[Question-ah]`, `[Question-ei]`, `[Question-en]`,
`[Question-oh]`, `[Surprise-wa]`, `[Surprise-yo]`, `[Dissatisfaction-hnn]`.
Respecter l'orthographe et la casse indiquées. Leur naturel en français avec
Ariane reste à écouter ; aucune règle universelle pour des didascalies françaises
arbitraires n'a été trouvée.
[Balises non verbales](https://voxcpm.readthedocs.io/en/latest/cookbook.html#extra-spice-non-verbal-tags).

Les virgules favorisent des pauses courtes ; points et questions des fins plus
marquées ; les points de suspension une hésitation. Le guide recommande de
fractionner les longues sorties, mais les entrées d'un seul mot peuvent aussi
être instables. Aucune syntaxe phonétique française n'y est spécifiée.
[Texte et pauses](https://voxcpm.readthedocs.io/en/latest/usage_guide.html#text-input).

Le français est pris en charge. Un accent régional précis ou une accentuation
sur un mot peuvent être demandés descriptivement, mais nous n'avons pas trouvé
de garantie ni de grammaire dédiée dans les pages consultées.
[Langues](https://voxcpm.readthedocs.io/en/latest/models/voxcpm2.html#language-support).

## Pauses exactes et artefacts

Ne pas présenter `<break time="500ms"/>` ou `[pause:1s]` comme une fonction
disponible. Une demande encore ouverte propose ces syntaxes. Son auteur rapporte
aussi des parenthèses placées au milieu du texte lues à voix haute ; il s'agit
d'un retour utilisateur sur 2.0.2, pas de notre mesure sur 2.0.3.
[Issue 276](https://github.com/OpenBMB/VoxCPM/issues/276).

Pour une pause exacte, notre application pourrait séparer les segments et
insérer du silence entre eux, en tenant compte des silences déjà générés. C'est
une proposition d'implémentation, pas une capacité acquise du modèle.

Le guide signale des artefacts possibles quand le guidage est fort ; il suggère
1,5–1,6 pour certaines sorties longues bruitées. Cela justifie un essai contrôlé,
pas une explication établie de notre son métallique. Le débruitage traite la
référence et peut modifier le timbre.
[Réglage de qualité](https://voxcpm.readthedocs.io/en/latest/usage_guide.html#quality-tuning).

## Conséquences pour notre intégration

Constats locaux :

- `vox_worker.py` construit déjà `(style)texte` et conserve les crochets.
- `serve.py` demande à Astra du texte sans didascalies et une direction globale ;
  il ne lui enseigne pas les balises non verbales documentées.
- Les espaces sont compactés : ajouter uniquement des retours à la ligne ne
  produit pas un contrôle de pause dans notre worker.
- Le code officiel retire les parenthèses internes de la direction avant de
  l'entourer. Notre assemblage ne le fait pas encore.

Proposition : conserver le profil approuvé et son identité, laisser Astra choisir
une direction compatible avec le contexte et quelques événements vocaux
facultatifs. Séparer le texte destiné au modèle des sous-titres lisibles ; garder
la provenance des deux. Aucun rire ni soupir obligatoire par réplique.

Exemple illustratif, non généré et non approuvé à l'écoute :

```text
(Warm conversational delivery, quietly delighted, relaxed pace.)
Oh… tu as pensé à moi ? [laughing] Merci, ça me fait vraiment plaisir.
```

Le préfixe d'identité stable et le profil existant restent gérés séparément dans
l'application ; cet exemple montre uniquement la direction variable et le texte.
Pour qualifier les crochets, comparer une réplique avec et sans une seule balise,
en gardant texte, référence, direction, graine et paramètres identiques ailleurs.
Vérifier le timbre, l'événement produit, les mots conservés et les éventuels
artefacts avant toute adoption. Ni changer la ponctuation, ni ajouter une balise
ne constitue une correction démontrée du timbre métallique.
