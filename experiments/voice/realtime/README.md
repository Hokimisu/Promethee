# Scène vocale expérimentale

Hermes produit une réplique courte et sa direction de jeu ; VoxCPM2 envoie le
PCM au navigateur pendant qu'ARDY génère la présence corporelle. Le même monde
enregistre les observations et les résultats d'outils. Cet essai de 60 secondes
reçoit des **interventions écrites**. Il ne valide pas encore le microphone,
l'interruption acoustique ou l'initiative persistante de T12.

Les sources sont livrées ; les modèles, références vocales, caches et sessions
restent locaux. Chaque lancement crée une nouvelle session de qualification,
exclue de la mémoire personnelle. Aucun scénario n'est prérempli. Les décors
sont visuels, pas des objets manipulables.

## Préparer les environnements

Le socle CPU utilise Python 3.12+ et les extras `agent` et `avatar`. Depuis un
clone neuf :

```sh
uv sync --locked --extra agent --extra avatar
npm --prefix web/avatar ci --ignore-scripts
node experiments/voice/realtime/web/build.mjs
```

Préparer ARDY, ses poids et son encodeur selon
[l'installation motrice](../../motion/README.md#reproduire-dans-wsl-ou-ubuntu).
Le rendu exige le [VRM pixiv épinglé](../../../docs/assets/pixiv-vrm-sample.md).
Préparer également [Hermes avec son authentification propre](../../../docs/hermes-setup.md).
La source Hermes qualifiée est `2179a279ae04bfadf8efbc49a01ca0abfb738000`
(0.21.3). Le chemin de l'interpréteur et celui du dépôt Hermes sont distincts.

Installer la voix dans un environnement **Linux x86_64 séparé**. Les commandes
suivantes sont en Bash, depuis le clone ; `VOICE_ENV` désigne un dossier neuf.
Elles ne modifient pas les environnements du socle, de Hermes ou d'ARDY.

```sh
VOICE_ENV="$HOME/.local/share/promethee/voice-env"
uv venv "$VOICE_ENV" --python 3.10
uv pip install --python "$VOICE_ENV/bin/python" torch==2.7.0+cu126 torchaudio==2.7.0+cu126 torchcodec==0.3.0+cu126 --index-url https://download.pytorch.org/whl/cu126
uv pip install --python "$VOICE_ENV/bin/python" -r experiments/voice/realtime/voice-requirements.txt
uv pip check --python "$VOICE_ENV/bin/python"
```

Installer les roues CUDA d'abord évite que l'index PyTorch masque des versions
de dépendances disponibles sur PyPI. Les 160 versions ont été réinstallées dans
un environnement neuf Python 3.10.12 avec uv 0.12.13 ; `uv pip check` réussit.
Les caches de téléchargement existants ont été réutilisés. Cela ne prouve pas
la compatibilité d'autres plateformes.

Télécharger le [snapshot officiel VoxCPM2](https://huggingface.co/openbmb/VoxCPM2/tree/32279effe8c19989596f05d353d1447f51d9e915)
à la révision `32279effe8c19989596f05d353d1447f51d9e915`. Par exemple, dans
le Python vocal :

```python
from huggingface_hub import snapshot_download

snapshot_download(
    "openbmb/VoxCPM2",
    revision="32279effe8c19989596f05d353d1447f51d9e915",
    local_dir="/path/to/VoxCPM2/32279effe8c19989596f05d353d1447f51d9e915",
)
```

Le worker utilise ensuite les fichiers locaux, sans téléchargement implicite.
Le SDK et le modèle VoxCPM2 conservent leur
[licence Apache 2.0](https://github.com/OpenBMB/VoxCPM). Le modèle qualifié
est une dépendance externe, pas un entraînement Promethee.

## Référence vocale

La référence d'Ariane approuvée n'est pas redistribuée. Pour conserver cette
voix sur la machine de qualification, fournir son cache existant et son
empreinte. Pour créer une autre référence à partir d'un WAV autorisé :

```sh
"$VOICE_ENV/bin/python" experiments/voice/realtime/prepare_reference.py --model-path /path/to/VoxCPM2/snapshot --wav /path/to/reference.wav --output /path/to/new-reference.pt
```

La commande affiche `reference_sha256` : c'est l'empreinte des octets du tenseur
`ref_audio_feat`, pas celle du fichier `.pt`. Elle conserve le mode référence
seule, sans transcription ou continuation du texte de référence. Un nouveau
cache exige une écoute ; il ne reproduit pas automatiquement la voix validée.
Le worker refuse une empreinte différente ou un cache de continuation.

Les réglages sont CFG 2, 10 pas, sortie 48 kHz, optimisation officielle et
générateur CUDA conservé sur son unique thread propriétaire. Les directions,
balises et ponctuations suivent le [contrat vocal](../../../docs/research/10-voxcpm-prompting.md).

## Encodeur de mouvement sans Llama résident

Sur la RTX 4080 de qualification, le modèle Llama de l'encodeur ne reste pas
chargé en même temps que Vox et ARDY. Avant de démarrer ces deux moteurs,
préparer les quatre textes du catalogue courant dans l'environnement encodeur :

```sh
/path/to/encoder-env/bin/python experiments/voice/realtime/encoder.py build --adapters /path/to/qualified-adapters --output /path/to/new-embeddings
/path/to/encoder-env/bin/python experiments/voice/realtime/encoder.py serve --output /path/to/new-embeddings --port 9551
```

La première commande calcule les vrais embeddings puis se termine. La seconde
ne charge aucun poids et répond sur CPU. Elle vérifie textes exacts, empreintes,
dimensions et valeurs finies ; un texte absent est refusé sans repli caché.
Il ne s'agit pas de mouvements enregistrés : ARDY génère de nouvelles poses.

## Configurer et lancer

Copier [config.example.json](config.example.json) vers un fichier local ignoré,
puis remplacer ses chemins. Les chemins du socle sont relatifs au fichier de
configuration. Les arguments de `voice_command` et les chemins d'ARDY sont
transmis tels quels, donc utiliser des chemins absolus du système qui les exécute.
Une commande vocale est une liste d'arguments, jamais une commande shell.

Pour Windows + WSL, définir `body.wsl` sur le nom de la distribution et utiliser
des chemins Linux pour `ardy_python` et `checkpoint_root`. Commencer
`voice_command` par `wsl.exe`, `-d`, le nom de distribution et `--exec`, suivis
du Python vocal Linux et du script accessible sous `/mnt/...`. Le socle, Hermes
et SQLite restent du même côté Windows. L'encodeur écoute sur l'URL configurée.

```sh
uv run --extra agent --extra avatar python experiments/voice/realtime/serve.py --config .local/realtime-config.json
```

Ouvrir l'URL locale affichée après construction du navigateur, attendre « Prête »,
écrire un contexte puis démarrer. Une intervention coupe la parole précédente
et invalide ses décisions tardives ; le bouton Arrêter demande aussi l'arrêt du
corps. Une commande acceptée n'est pas une action terminée. Le lancement refuse
un port occupé avant de charger les modèles.

Le préchauffage Hermes est activé dans cet essai. `resident` reste faux par
défaut dans la configuration ; le définir à `true` conserve une instance entre
les tours réussis avec reconnexion MCP. Ce mode a été qualifié avec Luna et
l'authentification native Hermes Codex. La voix et le corps restent chargés jusqu'à l'arrêt
du serveur. Les journaux et reçus de lecture sont enregistrés sous `data_dir`,
dans un nouveau sous-dossier à chaque lancement.

## Vérifier sans modèles

```sh
uv run --extra agent --extra avatar pytest -q experiments/voice/realtime
node --test experiments/voice/realtime/web/*.test.mjs
```

Les tests Python emploient des doublons pour les modèles. Les tests navigateur
vérifient buffers, annulation, ordre des événements et bouche liée au PCM joué.
Deux vérifications de médias privés sont ignorées sans `PROMETHEE_TEST_AVATAR`
(chemin VRM) et `PROMETHEE_TEST_VOICE` (WAV mono 48 kHz/16 bits). Avec les fichiers
locaux qualifiés, les 16 tests navigateur passent ; sans eux, 14 passent et 2
sont explicitement ignorés. Une suite verte ne prouve pas la fluidité du modèle.

La [qualification avec le résident](../../../docs/research/11-short-dialogue.md#scène-livrée-avec-hermes-résident)
utilise cet environnement vocal neuf et ces sources : dix réponses en 3,55 à
5,77 s, 54,40 s jouées pendant l'essai de 60 s, neuf lectures complètes puis
une coupure à l'échéance, sans sous-alimentation PCM. Un essai antérieur avait
échoué côté réseau ; le serveur réutilise désormais ses connexions HTTP. Ces
observations ne garantissent pas toutes les latences futures.

Le conflit de révision lors d'une
action explicite pendant la présence reste ouvert. Le compteur de 12 appels
et la fenêtre de 60 s appartiennent à cet essai ; ils ne remplacent pas le
budget persistant de l'initiative T12. Aucune conversation acoustique complète
n'est revendiquée par ce lancement.
