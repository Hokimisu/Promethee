# Essai ARDY

Qualification T02 en cours. Le modèle réel génère des poses dans le visualiseur officiel ; les mesures reproductibles sur des cas distincts restent à compléter. Les données, poids et environnements restent hors Git.

## Environnement observé

Le 15 septembre 2026 : Windows 11 x86_64, WSL Ubuntu 22.04, Python 3.11.16, RTX 4080 (16 376 MiB), pilote 596.21. WSL dispose d'environ 15 GiB de RAM et 4 GiB de swap. Un calcul PyTorch sur CUDA a réussi.

Le code ARDY est épinglé à `693f74d13b3d04a0a22ce127ee79c929dd89756b6c`. Le checkpoint téléchargé est `nvidia/ARDY-Core-RP-20FPS-Horizon40`, révision `abe6c43beb28c867c950acb824b9c4ef3d63fb76`. Son fichier de configuration indique 20 poses/s, un horizon de 40 images, des jetons de 4 images et 10 étapes de diffusion. Ce sont des paramètres du modèle, pas des performances mesurées.

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

Le service local de l'essai est `.local/encoder_service.py` ; ses copies préparées sont sous `/root/.local/share/promethee/text-encoders/`. Ce script exploratoire reste à transformer en commande reproductible documentée avant la clôture de T02.

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

## Preuves restantes

Fournir les scripts et versions verrouillées permettant de reproduire l'encodeur séparé ; exporter les conventions articulaires ; mesurer séparément première pose exploitable et blocs suivants sur des graines, départs, cibles et instructions variés, avec calibration et vérification distinctes. Vérifier séparément les licences du code, des checkpoints, de l'encodeur et des assets avant toute redistribution. Le choix de Viser pour T06 est étayé par cet essai, mais la décision et la qualification T02 ne sont pas encore closes.
