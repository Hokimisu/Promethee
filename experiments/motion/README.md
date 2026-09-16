# Essai ARDY

Essai T02 avec le modèle réel, sur des cas de calibration et de vérification distincts. Voir la [décision ARDY/Viser](../../docs/decisions/001-motion-stack.md) pour les conventions, licences et limites. Les données, poids et environnements restent hors Git.

## Environnement observé

Le 15 septembre 2026 : Windows 11 x86_64, WSL Ubuntu 22.04, Python 3.11.16, RTX 4080 (16 376 MiB), pilote 596.21. WSL dispose d'environ 15 GiB de RAM et 4 GiB de swap. Un calcul PyTorch sur CUDA a réussi.

Le code ARDY est épinglé à `693f74d13b3d04a0a22ce127ee79c929dd89756b`. Le checkpoint téléchargé est `nvidia/ARDY-Core-RP-20FPS-Horizon40`, révision `abe6c43beb28c867c950acb824b9c4ef3d63fb76`. Son fichier de configuration indique 20 poses/s, un horizon de 40 images, des jetons de 4 images et 10 étapes de diffusion. Ce sont des paramètres du modèle, pas des performances mesurées.

Installation effectuée dans un environnement WSL indépendant avec uv 0.12.5 :

```sh
uv venv /root/.local/share/promethee/ardy-env --python 3.11
uv pip install --python /root/.local/share/promethee/ardy-env/bin/python torch==2.14.0 torchvision==0.29.0 --index-url https://download.pytorch.org/whl/cu126
uv pip install --python /root/.local/share/promethee/ardy-env/bin/python -e '/mnt/g/Projects/Promethee/.local/ardy[demo]'
```

Cette installation a réussi, avec torch 2.14.0+cu126, transformers 5.8.1, peft 0.20.0 et numpy 1.26.4. Le visualiseur Viser provient du fork NVIDIA à `7c82ad8f8640bad9dff8ded5c5eee908eeb08f11`. Le paquet CPU Promethee n'a pas reçu ces dépendances.

## Poids de l'encodeur

L'accès officiel Meta a été accordé au propriétaire du compte. En parallèle, la copie publique [Nous Research](https://huggingface.co/NousResearch/Meta-Llama-3-8B-Instruct/tree/53346005fb0ef11d3b6a83b12c895cca40156b6c), révision `53346005fb0ef11d3b6a83b12c895cca40156b6c`, a été téléchargée sans authentification. Les quatre SHA-256 de poids annoncés par l'API Hugging Face correspondent à ceux de Meta ; il ne s'agit pas d'une version quantifiée.

Les deux adaptateurs restent ceux attendus par ARDY :

| Adaptateur McGill-NLP | Révision téléchargée |
|---|---|
| `LLM2Vec-Meta-Llama-3-8B-Instruct-mntp` | `31474e395ada192e8ed1586db6be79fb3b70c9c0` |
| `LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised` | `baa8ebf04a1c2500e61288e7dad65e8ae42601a7` |

Des copies locales des adaptateurs sont placées sous `/root/.local/share/promethee/text-encoders/McGill-NLP/`. Seuls `base_model_name_or_path` et `revision` de leur `adapter_config.json` pointent vers la copie Nous Research. Le cache partagé n'est pas modifié. Les fichiers `config.json` et tokenizers restent ceux de McGill, notamment l'identité Meta qui détermine le format du texte.

## Incompatibilité constatée

Le chargement local via le wrapper ARDY et Transformers 5.8.1 échoue avec : `OSError: Error no file named model.safetensors, or pytorch_model.bin, found in directory ...mntp`. La présence d'un `config.json` dans le dossier d'adaptateur empêche cette version de résoudre automatiquement sa base distante.

L'inspection du code installé montre aussi que `LlamaModel.forward` appelle désormais directement `create_causal_mask`, alors que le modèle bidirectionnel vendorié surcharge `_update_causal_mask`. Réparer uniquement le chemin des poids ne suffirait donc pas à garantir le calcul bidirectionnel attendu.

Les [dépendances officielles LLM2Vec](https://github.com/McGill-NLP/llm2vec/blob/main/setup.py) bornent Transformers entre 4.43.1 et 4.44.2. Un second environnement, destiné uniquement à l'encodeur, a été installé avec succès :

```sh
uv venv /root/.local/share/promethee/encoder-env --python 3.11
uv pip install --python /root/.local/share/promethee/encoder-env/bin/python torch==2.14.0 torchvision==0.29.0 --index-url https://download.pytorch.org/whl/cu126
uv pip install --python /root/.local/share/promethee/encoder-env/bin/python llm2vec==0.2.3 transformers==4.44.2 peft==0.13.2 gradio==5.49.1 numpy==1.26.4
```

Gradio 6.27.0 exige une version de huggingface-hub incompatible avec Transformers 4.44.2 ; Gradio 5.49.1 résout ces dépendances. Le raccord prévu par ARDY via Gradio sur `127.0.0.1:9550` a été vérifié : `TextEncoderAPI` retourne un tenseur `[1, 1, 4096]`, longueur `[1]`. Le service expérimental local utilise `LLM2Vec.from_pretrained`, fusionne MNTP comme prévu par ce chargeur, puis applique l'adaptateur supervised. Il conserve `meta-llama/Meta-Llama-3-8B-Instruct` dans la configuration et utilise bfloat16, sans quantification.

## Premières observations réelles

Le premier service local était `.local/encoder_service.py`. Il est remplacé par les scripts reproductibles ci-dessous, exercés avec les vrais poids et l'interface `TextEncoderAPI`.

Depuis le clone ARDY, après démarrage du service :

```sh
TEXT_ENCODER_MODE=api LOCAL_CACHE=true /root/.local/share/promethee/ardy-env/bin/python -u scripts/run_demo.py --no-compile
```

Ouvrir `http://localhost:2333`. Le visualiseur compile son client Viser au premier lancement. La génération, la lecture, la pause, le changement de prompt, l'affichage du squelette, le suivi caméra et l'export de session ont été exercés dans Chrome. L'absence des données Bones Seed désactive le tirage d'un mouvement de référence ; elle n'a pas empêché la génération.

| Mesure exploratoire | Résultat |
|---|---|
| Chargement LLM2Vec, poids déjà téléchargés | 94,74 s |
| Premier encodage, « A person walks forward. » | 17,92 s ; `[1,4096]`, valeurs finies |
| Pic mémoire PyTorch de l'encodeur | 15 654 216 192 octets (14,58 Gio) |
| Encodages ultérieurs observés | 0,13 à 3,32 s ; variabilité non encore caractérisée |
| Appel complet via `TextEncoderAPI`, texte inédit | 4,20 s, dont 2,51 s d'encodage serveur |
| Premier bloc Core, 40 poses | 0,891 s dans le journal du visualiseur |
| Cinq blocs suivants, puis premier bloc après changement de texte | 0,546 ; 0,343 ; 0,400 ; 0,259 ; 0,317 ; puis 0,847 s |
| Mise à jour d'un prompt inédit dans le visualiseur | 6,88 s |

Les durées du journal de génération ne couvrent pas toute la chaîne jusqu'à l'écran. Les 20 FPS affichés mesurent la lecture, pas la génération. L'essai n'utilise pas de compilation ONNX/TensorRT. Les graines de ces premières manipulations interactives n'ont pas été fixées : elles constituent une exploration, pas la batterie de vérification finale.

Deux exports locaux issus du visualiseur ont été relus :

- `.local/ardy/.cache/export/promethee-t02-text-change-01.pkl` : 554 poses à 20 FPS, 27 articulations, passage de marche à « A person stops walking and raises the left arm. ». Le bras levé a été observé dans le rendu. Toutes les positions et matrices exportées sont finies. L'arrêt précis et les contacts ne sont pas validés par cette observation.
- `.local/ardy/.cache/export/promethee-t02-velocity-01.pkl` : 447 poses, contrainte de vitesse XZ `[0.25, 0.1]` m/s appliquée depuis le panneau Generate. Après les deux premières secondes, la vitesse moyenne mesurée à partir de la racine est `[0.2232, 0.0833]` m/s. Les coordonnées restent finies ; cette erreur montre pourquoi une consigne ne peut pas être enregistrée comme un résultat exact.

Captures locales sous `.local/ardy/.cache/image_export/`, notamment `promethee-t02-velocity-01.png`. La caméra de suivi était trop éloignée pour juger les contacts : améliorer le cadrage et conserver des vidéos avant cette validation. Les exports pickle sont produits localement par cet essai ; ne pas charger de pickle non fiable.

## Reproduire dans WSL ou Ubuntu

Prérequis système de l'essai : Ubuntu 22.04 x86_64, pilote NVIDIA fonctionnel dans WSL, Git, compilateur C++, CMake et uv 0.12.5 disponible dans `PATH`. Prévoir environ 16 Go pour les seuls poids Llama, plus les environnements CUDA et leur cache. Les commandes suivantes s'exécutent dans **Bash**, depuis la racine du dépôt Promethee. `ROOT` désigne un dossier neuf ; les scripts refusent d'écraser une installation ou des résultats existants.

```sh
ROOT="$HOME/.local/share/promethee/reproduction"
PROJECT="$(pwd)"
bash experiments/motion/install.sh "$ROOT"
"$ROOT/ardy-env/bin/python" experiments/motion/prepare_encoder.py --directory "$ROOT/adapters"
"$ROOT/ardy-env/bin/python" experiments/motion/prepare_checkpoint.py --directory "$ROOT/checkpoints"
"$ROOT/encoder-env/bin/python" experiments/motion/encoder_server.py --adapters "$ROOT/adapters" --output "$ROOT/embeddings"
```

Laisser le dernier processus ouvert jusqu'à l'affichage de `http://127.0.0.1:9550`. Il garde l'encodeur en mémoire. Aucun token n'est nécessaire pour la copie publique vérifiée ; la licence Llama reste applicable. La préparation écrit `provenance.json` avec les révisions et SHA-256 annoncés, et ne modifie jamais le cache partagé. Les dépendances complètes sont dans [ardy-requirements.txt](ardy-requirements.txt) et [encoder-requirements.txt](encoder-requirements.txt). Le script installe d'abord les roues CUDA officielles, puis ces versions exactes et le clone ARDY épinglé ; il termine par deux contrôles de compatibilité des dépendances.

Dans un autre terminal Bash, depuis la même racine, redéfinir `ROOT` et `PROJECT` comme ci-dessus, puis :

```sh
"$ROOT/ardy-env/bin/python" experiments/motion/qualify.py --phase calibration --output .local/calibration-new --checkpoint-root "$ROOT/checkpoints"
"$ROOT/ardy-env/bin/python" experiments/motion/qualify.py --phase verification --output .local/verification-new --checkpoint-root "$ROOT/checkpoints"
"$ROOT/ardy-env/bin/python" experiments/motion/qualify.py --phase holdout --output .local/holdout-new --checkpoint-root "$ROOT/checkpoints"
"$ROOT/ardy-env/bin/python" experiments/motion/qualify.py --phase calibration --frames 40 --output .local/first-block-new --checkpoint-root "$ROOT/checkpoints"
uv run python experiments/motion/check_measurements.py .local/holdout-new/measurements.json
```

Les cas sont dans [qualify.py](qualify.py). Chaque dossier garde le script exact, les mesures, les conventions du squelette et les NPZ bruts/post-traités. Les critères de racine fixés après calibration sont dans [criteria.json](criteria.json). Le vérificateur exige trois cas distincts de 120 poses ; les essais de 40 poses servent uniquement à mesurer le premier bloc. Il ne valide pas le sens du geste, les pieds ou les collisions.

Pour examiner les poses dans le visualiseur officiel :

```sh
cd "$ROOT/ardy"
"$ROOT/ardy-env/bin/python" scripts/visualize.py "$PROJECT/.local/holdout-new" --port 2334
```

Ouvrir `http://localhost:2334`, choisir un fichier, activer le squelette, lire puis scruter les poses et les pieds. Le client Viser construit ses dépendances Web au premier lancement. Pour l'essai interactif avec changement de texte, depuis le clone :

```sh
TEXT_ENCODER_MODE=api LOCAL_CACHE=true "$ROOT/ardy-env/bin/python" scripts/run_demo.py --no-compile
```

Le visualiseur interactif utilise son propre chemin de cache et peut télécharger le checkpoint annoncé par son chargeur. Les mesures reproductibles ci-dessus imposent le dossier de checkpoint épinglé. Ne pas confondre un export interactif avec une batterie à graine fixée.

## Résultats conservés le 15 septembre 2026

| Dossier sous `.local/` | Résultat |
|---|---|
| `motion-calibration-01` | Échec de l'appel avec `progress_bar=None`, conservé ; remplacé par une fonction identité |
| `motion-calibration-02` | Graines 101–103, 120 poses ; base de calibration |
| `motion-verification-01` | Départs absolus mal interprétés : erreurs initiales de 0,67 à 1,10 m ; ne passe pas les critères |
| `motion-verification-02` | Graines 201–203 après conversion locale ; critères de racine respectés. Ces cas ont servi au diagnostic, donc ne sont plus indépendants |
| `motion-holdout-01` | Nouveaux cas 301–303 sans nouvelle correction ; trois réussites aux critères de racine |
| `motion-first-block-01` | Trois essais de 40 poses pour la latence, sans mélange avec la batterie de 120 poses |
| `motion-reproduction-01` | Trois séquences de 40 poses générées avec l'installation ARDY neuve `reproduction-03`, encodeur déjà chargé ; sorties finies |

| Graine réservée | Erreur initiale | Erreur cible après traitement | Plus grand pas de racine | Encodage API | Génération de 120 poses |
|---|---|---|---|---|---|
| 301 | 1,52 mm | 2,89 cm | 5,93 cm | 10,65 s | 4,76 s |
| 302 | 1,35 mm | 2,37 cm | 2,53 cm | 4,46 s | 0,94 s |
| 303 | 0,75 mm | 0,30 cm | 0,14 cm | 3,31 s | 0,82 s |

Le post-traitement de ces cas prend respectivement 1,08 s, 0,025 s et 0,017 s. Il ne remplace pas les trajectoires par leurs cibles. Les mesures dédiées de première pose sont de 0,518 / 0,198 / 0,225 s après encodage, soit 2,990 / 2,274 / 2,434 s texte compris ; ajouter 0,118 / 0,013 / 0,012 s pour le post-traitement. Ces durées excluent le rendu et son transport. Le premier bloc est nécessaire avant qu'une pose puisse être rendue : aucun streaming interne de diffusion n'est revendiqué.

L'installation neuve `reproduction-03` a reconstruit les deux environnements et l'extension C++ ; leurs dépendances passent `uv pip check`. Les essais précédents restent intacts. Deux premières tentatives ont révélé une faute de transcription du SHA ARDY dans la documentation : le SHA de 40 caractères ci-dessus est celui vérifié avec Git et utilisé par le script corrigé.

Les tests et captures ne constituent pas des souvenirs ni des consignes de vie. Les contacts du maillage, les annulations et les objets restent à qualifier lors de T07–T08. Une pose à la bonne cible ne prouve pas leur réussite.

## Comparer le contrôle et les corrections

Le [rapport de référence](../../docs/research/07-official-reference.md) décrit les
essais du 16 septembre et leurs limites. Les outils suivants utilisent l'environnement
ARDY isolé ; leurs sorties restent sous `.local/`, hors mémoire et hors Git.

- `continuous_trial.py` prolonge des poses corrigées et conserve les refus Core.
  `--history-limit`, `--arrival-stance` et `--root-path` sont des variantes de
  recherche, sans activation dans le contrôleur. Le contexte respecte 200 poses.
- `reference_trial.py` conserve les caractéristiques explicites du modèle, comme
  la démo brute ; `--feedback raw-poses` isole leur reconstruction. Les paramètres
  `--arrival-seconds 4 --settle-text "A person is standing."` testent une trajectoire
  de racine clairsemée puis un repos généré, sans imposer de pose terminale des jambes.
  La sortie ne certifie pas les appuis. `total_seconds` inclut les mesures et l'écriture.
- `compare_postprocessing.py --trial DOSSIER --output NOUVEAU_DOSSIER` compare les
  mêmes propositions avec le filtre officiel et avec notre correction archivée.
  Ce n'est pas une comparaison de boucles génératives indépendantes. Les durées
  partielles sont signalées ; les profils de contrainte non pris en charge sont refusés.

Pour les deux outils génératifs, fournir également `--source ARCHIVE.npz`,
`--checkpoint-root DOSSIER`, `--output NOUVEAU_DOSSIER`, `--seed ENTIER`,
`--text TEXTE` et `--target X Z`. Une archive source Core à 20 Hz est nécessaire.
Tous ces prompts restent des consignes d'essai, jamais une routine de l'avatar.
