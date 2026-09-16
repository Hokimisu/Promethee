# Scène vocale expérimentale

Hermes produit une réplique courte et sa direction de jeu ; VoxCPM2 envoie le
PCM au navigateur pendant qu'ARDY génère la présence corporelle. Le même monde
enregistre les observations et les résultats d'outils. On peut écrire dès que
la scène est prête, lancer un essai de 60 secondes, ou activer la transcription
locale facultative. Les essais numériques ne valident pas encore l'acoustique
du microphone de l'utilisateur. L'initiative est facultative, avec budget et
pause persistants ; sa qualification ne suffit pas à fermer T11–T12.

Les sources sont livrées ; les modèles, références vocales, caches et sessions
restent locaux. Par défaut, chaque lancement crée une nouvelle session de
qualification, exclue de la mémoire personnelle. Une reprise explicite est
possible avec `resume_world`. Aucun scénario n'est prérempli. Les décors
sont visuels, pas des objets manipulables.

## Préparer les environnements

Le socle CPU utilise Python 3.12+ et les extras `agent` et `avatar`. Depuis un
clone neuf :

```sh
uv sync --locked --extra agent --extra avatar
npm --prefix web/avatar ci --ignore-scripts
npm --prefix experiments/voice/realtime/web ci --ignore-scripts
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
La même règle s'applique à `asr_command`, facultative ; `null` garde le mode
texte sans charger de reconnaissance vocale.

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

## Initiative et reprise

Le bloc Initiative demande un budget de tours autonomes et une cadence explicites.
Il utilise le même `TextHost.initiative_tick` que le socle : un seul Hermes,
historique partagé, événements regroupés pendant la parole et budget réservé
atomiquement. Le bouton de démonstration n'ajoute aucun budget. Sans activation,
un contexte ou un message produit seulement sa réponse ; aucune consigne
« poursuis » n'est ajoutée automatiquement. L'essai de 60 secondes suspend
l'initiative lorsqu'il termine, même si du budget reste disponible.

Pause conserve le budget restant et coupe seulement une sortie autonome encore
en cours. Elle n'annule pas une réponse utilisateur plus récente ni une action
du corps. Arrêter suspend aussi l'initiative et garde sa portée sur le corps.
Un réveil peut rendre exactement `{"silent": true}` : ce résultat reste dans
l'historique natif, sans lancer Vox ni fabriquer de reçu de lecture.

La page doit avoir activé sa sortie audio par un geste explicite. Son signal
de présence renouvelle une disponibilité de 15 secondes ; fermer la page
empêche ensuite de nouveaux départs. Cette disponibilité n'est pas persistée.
Après redémarrage, même une initiative non suspendue attend donc l'activation
de la voix dans la page. Une décision déjà réservée consomme son budget même
si la sortie disparaît ; sans reçu navigateur, la lecture n'est pas déclarée
réussie.

Pour reprendre un monde, arrêter son ancien serveur puis ajouter à la
configuration locale :

```json
"resume_world": "realtime-runs/session-IDENTIFIANT/world"
```

Ce chemin est relatif au fichier de configuration. Il doit contenir une base
de qualification au schéma actuel ; une base personnelle, ancienne ou possédée
par un contrôleur actif est refusée. Aucune migration ni reconfiguration du
budget n'est implicite. Historique, budget et pause restent dans cette base.
La réconciliation existante restaure le dernier état confirmé, sans rejouer
un ancien mouvement. Les nouveaux journaux vocaux vont dans un nouveau dossier
de lancement ; les artefacts corporels de reprise vont dans
`world/body-resumes/<identifiant>/`.

Les routes locales `initiative_configure` et `initiative_pause` exposent ces
mêmes opérations au navigateur. Recharger le budget reste une action explicite
via la CLI du [contrat d'initiative](../../../docs/initiative.md), jamais un
effet de rechargement de page ou de démarrage de scène.

## Entrée vocale locale facultative

Installer [les dépendances ASR](asr-requirements.txt) dans un environnement
séparé. Le jeu de 26 versions a été installé et testé sur Windows x86_64 avec
Python 3.13.12 ; les autres plateformes ne sont pas qualifiées. Le moteur
utilise Faster Whisper sur CPU, en int8, quatre threads, langue française et
beam size 1. Il ne partage pas le GPU de Vox et ARDY.

```sh
uv venv .local/asr-env --python 3.13
uv pip install --python .local/asr-env/Scripts/python.exe -r experiments/voice/realtime/asr-requirements.txt
uv pip check --python .local/asr-env/Scripts/python.exe
```

Télécharger les quatre fichiers `config.json`, `model.bin`, `tokenizer.json`
et `vocabulary.txt` du [modèle small épinglé](https://huggingface.co/Systran/faster-whisper-small/tree/536b0662742c02347bc0e980a01041f333bce120)
vers un dossier local, par exemple avec `snapshot_download` et son argument
`allow_patterns`. Définir ensuite dans la configuration locale :

```json
"asr_command": [
  "C:/path/to/asr-env/Scripts/python.exe", "-X", "utf8",
  "C:/path/to/Promethee/experiments/voice/realtime/asr_worker.py",
  "--model-path", "C:/path/to/faster-whisper-small/536b0662742c02347bc0e980a01041f333bce120"
]
```

Le worker refuse un dossier incomplet et charge uniquement les fichiers
locaux. Faster Whisper, CTranslate2, Whisper et ce modèle converti sont sous
licence MIT ; les licences du détecteur navigateur et d'ONNX Runtime sont
conservées dans [THIRD_PARTY_NOTICES.txt](web/THIRD_PARTY_NOTICES.txt).

« Activer le micro » demande l'accès au périphérique ; aucun microphone n'est
ouvert au chargement de la page. Silero v5 détecte la parole dans le navigateur,
avec ses fichiers servis localement. Le navigateur demande suppression d'écho
et de bruit, dont l'efficacité dépend du matériel. Chaque segment dure au plus
12 secondes. Le PCM reste en mémoire ; seule sa transcription rejoint le même
contexte Hermes que les messages écrits. Une fermeture, un arrêt ou « Couper
le micro » libère les pistes.

Le début de parole coupe immédiatement la lecture locale ; l'acquittement du
serveur confirme l'invalidation durable du tour précédent. L'action corporelle
déjà acceptée reste active. La réponse suivante attend la fin du segment et sa
transcription. Une panne ASR, une permission refusée, un microphone absent ou
une capture périmée laisse le texte disponible. Le moteur ne se relance pas
automatiquement après panne : redémarrer la scène pour le réinitialiser.

Les résultats et limites de cette étape figurent dans
[la qualification microphone](../../../docs/microphone.md). Une transcription
peut se tromper ; l'interface affiche le texte reconnu.

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
locaux qualifiés, elles vérifient réellement les morphs et le WAV ; sans eux,
elles sont explicitement ignorées. Les tests micro utilisent des captures
simulées et couvrent aussi les permissions tardives, le nettoyage et les
réponses HTTP périmées. Une suite verte ne prouve pas la qualité acoustique.

La [qualification avec le résident](../../../docs/research/11-short-dialogue.md#scène-livrée-avec-hermes-résident)
utilise cet environnement vocal neuf et ces sources : dix réponses en 3,55 à
5,77 s, 54,40 s jouées pendant l'essai de 60 s, neuf lectures complètes puis
une coupure à l'échéance, sans sous-alimentation PCM. Un essai antérieur avait
échoué côté réseau ; le serveur réutilise désormais ses connexions HTTP. Ces
observations ne garantissent pas toutes les latences futures.

Le [conflit de révision pendant la présence](../../../docs/command-revision.md)
est corrigé et qualifié avec une vraie posture ARDY. Le compteur de 12 appels
et la fenêtre de 60 s appartiennent à cet essai ; ils ne remplacent pas le
budget persistant de l'initiative T12. Aucune conversation acoustique complète
n'est revendiquée par ce lancement.
