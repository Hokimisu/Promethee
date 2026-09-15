# ARDY Core et Viser pour le premier corps

Décision du 15 septembre 2026, ticket T02. Les scripts et la procédure sont dans [l'essai moteur](../../experiments/motion/README.md). Cette décision sélectionne une génération cinématique ; elle ne valide pas les contacts ni les interactions T07–T08.

## Choix

Utiliser ARDY Core, checkpoint `ARDY-Core-RP-20FPS-Horizon40`, et le visualiseur Viser du dépôt officiel. Le visualiseur charge le squelette, anime son maillage et permet d'inspecter des poses enregistrées. Aucun besoin constaté ne justifie un autre moteur pour T06.

L'adaptateur Promethee est `src/promethee/viewer.py`, lancé avec `uv run --extra viewer promethee-view --database <base.sqlite3> --skeleton <conventions.json>`, éventuellement `--motion <poses.npz>`. La [procédure de rendu](../rendering.md) décrit son installation, ses repères et son fonctionnement en lecture seule.

Conserver deux environnements Python 3.11 : ARDY et l'encodeur LLM2Vec. Les versions compatibles de Transformers diffèrent. L'API Gradio locale déjà prévue par ARDY assure leur liaison ; le socle Python 3.12+ garde ses dépendances indépendantes. Le moteur devra recevoir des contraintes et retourner les poses observées, sans écrire un succès à partir du seul texte.

## Conventions relevées

- Core possède 27 articulations. Chaque essai exporte leurs noms, parents, positions neutres et quatre articulations de pied dans `conventions.json`, depuis le squelette chargé. Ne pas recopier un squelette G1 ou humain générique.
- Les positions sont en mètres, Y vers le haut, sol XZ. La position logique `[x, y]` devient `[x, hauteur, y]`. Une case d'un mètre doit conserver cette dimension dans le rendu.
- Le cap nul regarde vers +Z. Une rotation positive autour de Y tourne +Z vers +X : la matrice est `[[cos,0,sin],[0,1,0],[-sin,0,cos]]`. Les angles sont en radians, les matrices agissent sur des vecteurs colonnes ; le code peut stocker les positions en lignes et multiplier par la transposée.
- Les sorties contiennent des matrices locales et globales 3 × 3. Viser utilise des quaternions `w,x,y,z` ; ne pas lui donner l'ordre `x,y,z,w`.
- `root_positions` représente les hanches, articulation `Hips`, et non un point sur le sol. `posed_joints` contient les positions mondiales des articulations. Les NPZ enregistrés ont des dimensions `[T,27,3]`, `[T,27,3,3]` et `[T,3]`, sans dimension de batch.
- Le modèle produit 20 poses/s, par blocs de 40 poses dans cet essai. La cadence d'affichage n'est pas une mesure de vitesse d'inférence.
- L'appel batch essayé part d'une origine XZ nulle. Les contraintes doivent être relatives au départ ; on translate ensuite **toute** la trajectoire observée dans le monde. L'essai fautif et sa correction restent conservés. L'interface autorégressive possède une translation initiale à vérifier lors de T07.

Sources de ces conventions : `ardy/motion_rep/tools.py`, `ardy/skeleton/`, `ardy/viz/viser_utils.py` et exports du modèle, au commit `693f74d13b3d04a0a22ce127ee79c929dd89756b`.

## Mesures et portée

Sur RTX 4080 16 Go, les trois cas réservés après la correction de coordonnées atteignent leur cible avec 0,30 à 2,89 cm d'erreur ; l'erreur initiale est inférieure à 1,6 mm. Aucun ne dépasse le seuil fixé de 12 cm entre deux positions de racine. Les poses sont finies. Ce contrôle de racine ne mesure ni collision ni glissement du maillage.

Un bloc de 40 poses devient disponible en 0,20 à 0,52 s après encodage ; texte et génération prennent 2,27 à 2,99 s dans l'essai dédié, avant post-traitement et transport vers l'écran. Les blocs suivants de la batterie réservée prennent 0,22 à 0,31 s. Le premier appel après chargement est nettement plus lent. Le chargement de l'encodeur a pris 94,74 puis 157,42 s, poids déjà présents ; son allocation GPU atteint 14,58 Gio, contre environ 0,87 Gio pour ARDY. La marge GPU est étroite.

Les observations interactives montrent la marche, un changement de texte suivi d'un bras levé et une contrainte de vitesse. Dans le cas `203`, les deux mains passent au-dessus de la tête vers les poses 15–19, puis sont redescendues à la pose 100 : le prompt ne maintient pas automatiquement une posture finale. T07 doit donc mesurer une posture réellement obtenue et traiter les transitions ainsi que l'annulation.

Cette configuration peut alimenter un prototype interactif après préchargement. Elle ne garantit pas une réponse immédiate à un texte inédit. Garder la lecture des poses indépendante du raisonnement et de l'encodage.

## Provenance et licences

| Élément | Source et licence constatée | Utilisation retenue |
|---|---|---|
| Code ARDY | [Dépôt NVIDIA](https://github.com/nv-tlabs/ardy/tree/693f74d13b3d04a0a22ce127ee79c929dd89756b), Apache-2.0 | Installation séparée, aucune copie du code dans le paquet CPU |
| Poids Core | [Fiche NVIDIA](https://huggingface.co/nvidia/ARDY-Core-RP-20FPS-Horizon40), NVIDIA Open Model Agreement | Téléchargement local de la révision épinglée ; aucun poids dans Git |
| Code LLM2Vec | [McGill](https://github.com/McGill-NLP/llm2vec), MIT | Paquet officiel 0.2.3 dans l'environnement encodeur |
| Adaptateurs McGill | [Fiche des adaptateurs](https://huggingface.co/McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised), MIT annoncé | Les droits sur la base Llama restent distincts |
| Base Llama 3 | [Modèle Meta](https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct), Llama 3 Community License | Copie Nous Research de mêmes SHA-256 ; accès Meta accepté par l'utilisateur |
| Viser | [Fork NVIDIA](https://github.com/nv-tlabs/kimodo-viser/tree/7c82ad8f8640bad9dff8ded5c5eee908eeb08f11), Apache-2.0 | Dépendance épinglée de l'essai |
| Squelette et peau Core | `ardy/assets/skeletons/cskel27/` dans le clone NVIDIA | Le dépôt distingue code et données ; aucune licence spécifique supplémentaire trouvée dans ce dossier. Charger localement l'asset du visualiseur, sans le redistribuer ni prétendre lui attribuer la licence MIT de Promethee |

Le jeu de données Bones et les assets supplémentaires ne sont pas nécessaires à cet essai et ne sont pas téléchargés. Une redistribution de l'apparence demandera une provenance explicite ou un asset original. Les critères ci-dessus portent sur la capacité technique du moteur, pas sur une routine ou une identité de l'avatar.
