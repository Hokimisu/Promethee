# Voix locale expressive pour Ariane

Recherche et essais du **16 septembre 2026**. La voix Qwen a été approuvée par l’utilisateur et sert de référence synthétique. Après écoute des nouvelles versions, **l’utilisateur classe VoxCPM2 optimisé premier, Confucius4 deuxième et OmniVoice troisième**. Il garde OmniVoice comme alternative si Vox n’est pas assez rapide en situation réelle. Dots et Sopro lui paraissent robotiques, avec un rejet particulièrement marqué de Sopro. Ce jugement porte sur les extraits testés, pas sur toutes les configurations possibles. AuK-Flash est également demandé pour compléter la comparaison.

**VoxCPM2 optimisé est le candidat principal pour la suite ; Confucius4 reste l’alternative de qualité et OmniVoice celle de rapidité.** La vitesse CPU de Sopro ne compense pas le défaut perçu à l’écoute. Son audit de format et d’export n’a pas démontré de bug d’intégration ; les variantes de contrôle restent distinctes de l’échantillon rejeté. Les mesures de débit ne remplacent pas le jugement de qualité et ne fixent pas la limite des modèles avec d’autres moteurs d’inférence.

Les versions majeures Qwen, Fish et Vox présélectionnées datent de janvier, mars et avril 2026. Les nouvelles propositions Confucius4 et Sopro sont plus récentes. Les révisions exactes testées figurent ci-dessous.

## Mesure Qwen effectuée

L’essai `.local/voice-qwen-01/report.json` a réutilisé l’installation et le cache existants (`G:/Projects/AI_Server/Qwen3-TTS`), sans nouvelle installation pour cet essai. Il a produit `ariane-qwen-anger.wav` en local, sans réseau pendant la génération. Le modèle et la révision sont ceux de VoiceDesign indiqués plus bas.

| Mesure du premier essai SDPA | Résultat |
|---|---:|
| Audio à 24 kHz | 8,8 s |
| Génération | 31,294 s |
| RTF de cet essai | 3,556 |
| Pic de mémoire GPU rapporté par le script | 4,153 GiB |
| Torch | 2.5.1+cu124 |

La voix a été approuvée à l’écoute par l’utilisateur. **Ce premier essai à froid ne mesure pas le débit stabilisé ou la limite de vitesse de Qwen.** Il ne mesure pas non plus le délai du premier fragment en streaming.

Le second essai, archivé dans `.local/voice-qwen-01/stream-report.json`, réutilise cette voix avec **Qwen3-TTS-12Hz-1.7B-Base**, révision `fd4b254389122332181a7c3db7f27e918eec64e3`. Le profil ICL persistant pèse **18 336 octets** : extraction en **17,019 s**, rechargement en **0,015 s**. Ce profil évite le réencodage de la référence ; il ne contient pas les poids et ne supprime pas le calcul de chaque nouvelle phrase.

| Mesure Base, six répliques | Résultat |
|---|---:|
| Chargement du modèle | 7,722 s |
| Premier PCM de la première réplique | 2,762 s |
| Premier PCM des cinq suivantes | 1,397–1,615 s |
| Durée des sorties | 4,725–6,203 s |
| Temps de génération par réplique | 18,171–24,280 s |
| RTF | 3,452–4,087 |
| Attente initiale minimale calculée pour une lecture sans trou | 13,249–18,397 s |
| Pic mémoire GPU rapporté | 4,172 GiB |

Il s’agit du **fork streaming local**, avec FlashAttention 2 et quatre threads, pas du seul paquet officiel. Source utilisée : `G:/Projects/AI_Server/Qwen3-TTS-streaming`, HEAD `b8db6ff1cebc0d6554cf0977045850bcc796b383` ; les hashes des fichiers sont dans `source-provenance.json`. Le profil rechargé et les fragments PCM sont bien mesurés. En revanche, les changements simultanés de modèle, d’implémentation, d’attention et d’état chaud interdisent d’attribuer un gain au seul profil. La première voix approuvée et la reproduction par Base doivent aussi être distinguées à l’écoute.

## Mesure VoxCPM2 effectuée

L’essai `.local/voice-voxcpm-01/benchmark.json` contient deux appels à l’API officielle `generate_streaming`, avec le même texte que le premier Qwen et **sa référence vocale synthétique approuvée**. Chaque sortie contient 46 fragments PCM de 160 ms à 48 kHz. Le modèle est chargé une seule fois, en **26,675 s**, puis testé à froid et à chaud. Les temps ci-dessous excluent ce chargement et l’écriture du WAV ; ils incluent le traitement de la référence à chaque appel.

| Mesure | Premier appel | Appel chaud |
|---|---:|---:|
| Durée audio | 7,360 s | 7,360 s |
| Génération complète | 23,104 s | 15,643 s |
| Premier PCM disponible | 8,666 s | **0,411 s** |
| RTF | 3,139 | **2,125** |
| Pic alloué par PyTorch | 5,537 GiB | 5,642 GiB |
| Pic réservé par PyTorch | 5,877 GiB | 6,014 GiB |
| Attente initiale minimale calculée sans trou | 15,903 s | **8,442 s** |

Les deux WAV sont finis, sans NaN, sans écrêtage et sans atténuation ajoutée. Fichiers : `.local/voice-voxcpm-01/ariane-voxcpm-cold.wav` et `ariane-voxcpm-warm.wav`. L’utilisateur a retenu cet échantillon comme le meilleur du premier comparatif. La fidélité sur d’autres textes et styles reste à éprouver.

L’audit CPU `playback-diagnostic.json` calcule `max(arrivée_du_fragment − durée_des_fragments_précédents)`. Le premier PCM chaud à 0,411 s ne permet donc pas de démarrer et continuer immédiatement : il faut environ **8,44 s** de délai initial dans cette trace pour éviter les interruptions, hors transport et périphérique audio. Il s’agit d’un calcul sur les arrivées, pas d’une latence sonore mesurée au haut-parleur. Les pics PyTorch ne représentent pas toute l’occupation de la carte.

### VoxCPM2 optimisé sous WSL

L’essai `.local/voice-voxcpm-02/benchmark.json` conserve les poids, VoxCPM
2.0.3, le texte, la référence, la direction, les dix étapes et le guidage 2.
Un environnement WSL neuf utilise Python 3.10.12, Torch 2.7.0+cu126,
Triton 3.3.0 et Transformers 4.57.3. Le profil officiel de référence est
réutilisé et l’optimisation native `tts_model.optimize()` compile les quatre
composants prévus par le paquet, sans quantification ni Nano-vLLM.

| Mesure, profil prêt | WSL sans compilation | Compilé chaud 1 | Compilé chaud 2 |
|---|---:|---:|---:|
| Durée audio | 7,360 s | 7,360 s | 7,360 s |
| Génération complète | 11,091 s | 4,947 s | 5,255 s |
| Premier PCM | 0,801 s | 0,093 s | 0,093 s |
| RTF complet | 1,507 | 0,672 | 0,714 |
| Attente initiale idéale sans coupure | 3,890 s | 0,093 s | 0,093 s |
| Pic alloué par PyTorch | 5,537 GiB | 5,459 GiB | 5,459 GiB |

Le modèle chargé est identique entre le contrôle WSL et les appels compilés :
le gain attribuable à la compilation est ici de 2,1 à 2,2 fois. Le gain global
par rapport aux 15,643 s Windows comprend aussi le système, Torch et le profil.
Chargement (30,283 s), création initiale du profil (16,410 s) et premier passage
de compilation/échauffement (114,163 s) sont mesurés séparément. Quatre graphes
sont capturés ; aucun nouveau graphe n’est compilé pendant les deux appels chauds.

Les 46 vrais fragments de 160 ms permettent une consommation simulée sans
interruption dès le premier fragment sur ces deux traces. **Ce n’est pas une
latence sonore mesurée au haut-parleur**, ni une qualification avec ARDY ou des
textes nouveaux. Les sorties compilées sont identiques pour cette graine,
finies et sans saturation, mais diffèrent de la sortie sans compilation :
`ariane-voxcpm-warm-2.wav` est ajouté au comparatif sans remplacer la voix
approuvée. L’utilisateur a depuis écouté cette version compilée et l’a classée
première, devant Confucius4 et OmniVoice.

Le profil de référence de 58 024 octets se recharge en 15,7 ms avec égalité
des tenseurs vérifiée. Il doit rester sur CPU pour cette API. Le modèle et son
décodeur ont des états mutables ; un seul thread doit posséder le générateur.
Une fermeture après deux fragments, au point de retour du générateur, prend
0,462 ms et permet une nouvelle génération valide. Cette sonde ne mesure pas
l’interruption d’un calcul CUDA actif. Le raccord vocal du runtime reste à faire.

## Mesure Confucius4 effectuée

L’essai `.local/voice-confucius4-01/benchmark.json` utilise un environnement
WSL neuf : Python 3.10.12, Torch/torchaudio 2.7.0+cu126, Transformers 4.52.4.
Le modèle reçoit la référence Qwen entière, sans transcription, et le code de
langue `fr`. Les deux appels reprennent le même texte et la graine 91626.
Le traitement de la référence est inclus à chaque appel, le chargement du
modèle de **34,412 s** est mesuré séparément. Aucun autre moteur ne génère sur
le GPU pendant ces appels.

| Mesure HF, paramètres officiels | Premier appel | Appel chaud |
|---|---:|---:|
| Durée audio à 22 050 Hz | 7,059 s | 7,059 s |
| Génération et premier PCM complet | 11,738 s | 9,495 s |
| RTF | 1,663 | 1,345 |
| Pic alloué par PyTorch | 6,487 GiB | 6,596 GiB |

L’API testée retourne la phrase complète. **Ce n’est pas une mesure de
streaming** : les 9,495 secondes précèdent tout PCM utilisable dans ce chemin.
Le backend vLLM officiel propose du streaming mais n’a pas été installé pour
ce premier essai. Les paramètres conservés comprennent trois faisceaux de
recherche et 25 étapes acoustiques ; aucun gain d’optimisation n’est supposé.
Les WAV `ariane-confucius-cold.wav` et `ariane-confucius-warm.wav` sont locaux.

Le code testé est [`4fb32c481302d8858c3aec6a1c2a8b4cea8894c0`](https://github.com/netease-youdao/Confucius4-TTS/tree/4fb32c481302d8858c3aec6a1c2a8b4cea8894c0),
les poids [`696981f4520eae8f9f088f2dce0161d11cd67829`](https://huggingface.co/netease-youdao/Confucius4-TTS/tree/696981f4520eae8f9f088f2dce0161d11cd67829),
tous deux déclarés Apache-2.0. Les dépendances de modèle sont aussi fixées :
W2v-BERT `da985ba0987f70aaeb84a80f2851cfac8c697a7b` (MIT),
CAMPPlus `e4b6ede7ce16997aff4ae69fbca1f0175e2afede` (Apache-2.0),
BigVGAN `633ff708ed5b74903e86ff1298cf4a98e921c513` (MIT).
Le manifeste local conserve les chemins et environ 5,86 Go de poids utiles,
chargés hors ligne sans modifier les environnements ARDY ou Qwen.

## Mesures dots.tts effectuées

Les deux variantes sont générées successivement sur la RTX 4080, dans un
environnement WSL distinct, Python 3.11.16 et Torch/torchaudio 2.8.0+cu126.
L’API `DotsTtsRuntime.generate_stream` fournit de vrais fragments PCM à
48 kHz, avec la langue `FR`, le même texte et la référence synthétique Qwen.
La graine 42 est réinitialisée avant chacun des deux appels par variante.
Le journal est `.local/voice-dots-01/benchmark.json`.

| Mesure à chaud, sans compilation | MF 2 steps | SOAR |
|---|---:|---:|
| Premier PCM | 0,480 s | 0,858 s |
| Durée audio | 8,480 s | 7,200 s |
| Génération complète | 10,225 s | 19,394 s |
| RTF | 1,206 | 2,694 |
| Pic alloué par PyTorch | 5,18 GiB | 5,18 GiB |

Le départ calculé permettant une lecture sans interruption est de **1,921 s**
pour MF et **12,362 s** pour SOAR à chaud. Les dates d’arrivée sont enregistrées ;
les tailles des fragments sont reconstruites depuis le chemin eager officiel
(80 ms au début, 160 ms au milieu, 80 ms au dernier fragment), avec vérification
exacte contre la durée des WAV. Cette provenance diffère des tailles directement
enregistrées chez Vox et Sopro. Les quatre WAV sont finis, sans saturation,
et identiques entre premier et second appel pour chaque variante et cette graine.

MF utilise deux étapes acoustiques ; SOAR en utilise dix avec son guidage par
défaut. Ces paramètres officiels sont conservés. Le premier appel MF demande
31,639 s après 45,567 s de chargement séparé ; son premier PCM arrive après
21,441 s, initialisation des bibliothèques audio comprise. Le premier appel
SOAR charge un nouveau modèle dans le même processus ; les bibliothèques audio
sont donc déjà initialisées. Ces premiers appels ne mesurent pas des caches
disque froids identiques. Aucun jugement de diction ou d’émotion ne découle du
seul débit.

Le dépôt demandé est un fork de `studio-dots-ai/dots.tts`. Code testé :
[`4947d364baa5afb2daf1feb00a247b5f23f97878`](https://github.com/whk-sjtu/dots.tts-public/tree/4947d364baa5afb2daf1feb00a247b5f23f97878).
Poids MF : [`159b33d33de0f9610d9ea73725a0820d27261fd7`](https://huggingface.co/dots-studio/dots.tts-mf-2steps/tree/159b33d33de0f9610d9ea73725a0820d27261fd7) ;
SOAR : [`2f9b3e18d70d670d4c701da2dc55ded5755815ce`](https://huggingface.co/dots-studio/dots.tts-soar/tree/2f9b3e18d70d670d4c701da2dc55ded5755815ce).
Code et poids déclarent Apache-2.0. Les snapshots déjà présents sur C: ont été
réutilisés sans téléchargement des poids.

L’installation utilise seulement l’API : Gradio 6.17.0 demandé par le dépôt
était absent de l’index. La dépendance `pynini` empêchait l’installation Windows,
d’où WSL. Les versions compatibles Transformers 4.57.3 et safetensors 0.8.0
remplacent respectivement une version retirée et une préversion. Le code du
modèle reste intact ; ces écarts d’environnement sont consignés dans le rapport.
Transformers émet aussi un avertissement sur la regex du tokenizer Mistral ;
il n’a pas été masqué ou corrigé dans cet essai. Son impact sur la diction
française reste à évaluer.

## Mesures Sopro v2 Turbo effectuées

Le paquet officiel `sopro==2.2.0` tourne sous Windows avec Python 3.12.12 et
Torch 2.5.1, **sur le Ryzen 7 5800X3D, quatre threads, FP32, CUDA masqué**.
Le modèle est chargé en 1,508 s. La référence et ses états de streaming sont
préparés une fois en 0,595 s, puis réutilisés en mémoire. Ce coût est séparé
du tableau ; cette voie n’a pas encore été raccordée au runtime d’Ariane.

| Mesure CPU, profil prêt | Premier appel | Appel suivant |
|---|---:|---:|
| Durée audio à 24 kHz | 7,371 s | 7,371 s |
| Génération complète | 4,788 s | 5,062 s |
| Premier PCM | 0,923 s | 0,974 s |
| RTF | 0,650 | 0,687 |
| Attente initiale minimale calculée sans interruption | 0,923 s | 1,094 s |
| Pic mémoire résidente du processus | 1,332 GiB | 1,396 GiB |

Avec la préparation de référence incluse, le premier PCM du premier appel
demande 1,517 s, toujours hors chargement. Onze fragments PCM sont effectivement
produits par appel. Le délai sans interruption est calculé depuis leurs
arrivées et durées, hors transport et périphérique ; ce n’est pas une lecture
chronométrée au haut-parleur. Deux appels sur une seule phrase ne qualifient
pas une conversation prolongée ou l’exécution simultanée avec ARDY.

Les WAV `.local/voice-sopro-01/ariane-sopro-cold.wav` et
`ariane-sopro-warm.wav` sont identiques pour cette graine 42, finis, sans
écrêtage ni gain d’export ajouté. Les traitements officiels de normalisation
de référence et le limiteur doux de sortie sont conservés. Le texte est celui
des autres essais, avec `lang='fr'`. **L’API n’expose pas de prompt d’émotion** :
le jeu vocal dépend ici de la référence. L’utilisateur a rejeté la qualité de
cet extrait, malgré sa rapidité. Aucun profil Sopro n’a encore été
persisté sur disque.

Un diagnostic séparé dans `.local/voice-sopro-01/diagnostic-01/report.json`
vérifie les poids strictement chargés, le calcul CPU FP32, la référence et la
sortie mono 24 kHz, ainsi que la balise française. Deux appels officiels avec
référence fraîche, `stream` et `synthesize`, produisent des fichiers de contrôle.
Pour le même nouveau flux, notre exporteur et `tts.save_wav` produisent des
octets WAV identiques : aucune déformation par concaténation ou export n’est
démontrée. La référence expressive, le chemin streaming ou les deux étapes
acoustiques restent des hypothèses de qualité, pas des causes établies. Les
nouvelles variantes n’ont pas été approuvées à l’écoute. L’original est conservé.

Poids : [`samuel-vitorino/sopro-v2-turbo@f747f9edfb7b0233a3b7105af3a75603a7213d26`](https://huggingface.co/samuel-vitorino/sopro-v2-turbo/tree/f747f9edfb7b0233a3b7105af3a75603a7213d26).
Code Git consulté : [`7bfcf9a0539d274f6593959a21da948f506ceee1`](https://github.com/samuel-vitorino/sopro/tree/7bfcf9a0539d274f6593959a21da948f506ceee1) ;
le code exécuté est le paquet PyPI 2.2.0. Les poids et le code déclarent
Apache-2.0. Les 634 Mo de fichiers téléchargés restent dans le cache local,
hors Git. Le journal `.local/voice-sopro-01/benchmark.json` conserve les mesures
et la provenance. [Présentation des auteurs](https://research.haloneuro.ai/posts/sopro-v2).

Les environnements, le traitement de référence, les bibliothèques et les
possibilités de direction émotionnelle diffèrent entre moteurs. Il s’agit
d’essais d’intégration sur cette machine, pas d’un classement universel de
qualité ou de performances. La phrase cible reprend en outre le texte de la
référence : la fidélité sur de nouvelles phrases reste à éprouver après écoute.

## Mesures OmniVoice effectuées

OmniVoice a généré deux fois le même texte français avec la référence Qwen
inchangée et sa transcription. L’API officielle `generate()` fournit une
phrase complète à 24 kHz ; **cet essai ne mesure pas de streaming**. Les
32 étapes et les pré/post-traitements officiels sont conservés, avec FP16,
SDPA et graine 42 réinitialisée. Aucun ASR, FlashInfer ou compilation n’est
activé. Le prétraitement de référence reste dans chaque appel chronométré.

| Mesure | Premier appel | Appel chaud |
|---|---:|---:|
| Durée audio | 8,520 s | 8,520 s |
| Génération et phrase complète disponible | 2,952 s | 1,606 s |
| RTF | 0,346 | 0,189 |
| Pic alloué par PyTorch | 2,151 GiB | 2,151 GiB |

Le chargement de 10,213 s est séparé. Les WAV sont identiques pour ces deux
appels, finis et sans écrêtage ; la référence reste identique avant/après.
Fichier d’écoute : `.local/voice-omnivoice-01/ariane-omnivoice-warm.wav`.
L’utilisateur juge cet extrait satisfaisant et le classe troisième derrière
VoxCPM2 optimisé et Confucius4. Sa rapidité justifie de le conserver si Vox
ne tient pas la cadence en situation réelle ; aucun basculement automatique
de moteur n’est implémenté ou demandé à ce stade.

Environnement WSL neuf, Python 3.11.16, Torch 2.8.0+cu126, Transformers 5.8.1.
OmniVoice 0.2.1 est construit et installé depuis le checkout Git ci-dessous,
pas depuis sa wheel PyPI : les 48 fichiers Python installés sont identiques au
checkout propre, avec `direct_url.json` et hashes archivés. Code exécuté :
[`08be0b4ccbac3e13e374e86fbfead4b4cac343e2`](https://github.com/k2-fsa/OmniVoice/tree/08be0b4ccbac3e13e374e86fbfead4b4cac343e2) ;
poids : [`c5fdb5ccb189668d56333f77ba2629f4cd7535f4`](https://huggingface.co/k2-fsa/OmniVoice/tree/c5fdb5ccb189668d56333f77ba2629f4cd7535f4).
Le code est Apache-2.0, les poids CC-BY-NC selon leur fiche ; le codec embarqué
possède sa licence Boson Higgs Audio 2 Community distincte. Ce périmètre diffère
des poids Apache de Vox. Le journal local conserve les versions effectivement
importées, paramètres, hashes et mesures. [Fiche officielle](https://huggingface.co/k2-fsa/OmniVoice).

## AuK-Flash : essai avec correctif mémoire

Le chemin officiel avec déchargement CPU annonce encore 16,75–16,98 GiB de
mémoire graphique dans ses exemples, au-delà de la capacité de notre 4080.
L’inspection trouve une conversion globale FP32 qui double inutilement le
stockage de l’encodeur Qwen initialement chargé en BF16. Un correctif proposé
dans les [PR 18](https://github.com/Tencent-Hunyuan/AuK/pull/18) et
[PR 12](https://github.com/Tencent-Hunyuan/AuK/pull/12) fournit une voie à tester.
Nous remplaçons uniquement `model.to(torch.float32)` par
`model.transformer.to(torch.float32)` dans une copie isolée, puis activons
`cpu_offload=True`. Les paramètres de fusion et le VAE restent FP32 ; le
chargement vérifie effectivement Qwen BF16. **Il s’agit d’une variante locale
corrigée, pas de performances du code officiel inchangé.**

Deux appels sont terminés sous Windows, Python 3.10.19, Torch 2.7.1+cu126 et
Transformers 4.57.3, dans un environnement distinct. Ils utilisent la même
référence synthétique et la même phrase française. La durée demandée de 8,8 s
est arrondie à 8,82 s par le modèle. Les quatre étapes et le guidage nul
imposés par Flash restent intacts, sans service externe de préparation du prompt.

| Mesure, avec correctif et déchargement CPU | Premier appel | Appel chaud |
|---|---:|---:|
| Durée audio à 24 kHz | 8,820 s | 8,820 s |
| Génération et phrase complète disponible | 58,315 s | 11,705 s |
| RTF | 6,612 | 1,327 |
| Pic alloué par PyTorch | 9,535 GiB | 9,963 GiB |
| Pic réservé par PyTorch | 9,734 GiB | 10,189 GiB |

Le chargement de 21,094 s est séparé. La mesure inclut les transferts CPU/GPU
et le retour de la forme d’onde sur CPU, sans streaming ni lecture au haut-parleur.
Le système dispose de peu de RAM libre pendant l’essai ; les chiffres incluent
cette situation et ne définissent pas un plafond de performance du modèle.
Les deux WAV sont finis et sans écrêtage, mais diffèrent malgré la même graine.
Fichier d’écoute : `.local/voice-auk-01/ariane-auk-flash-warm.wav` ; mesures et
empreinte du fichier source corrigé dans `benchmark.json`.

La fiche des poids annonce chinois et anglais, **pas le français** : cette
synthèse française reste exploratoire, et sa réussite technique ne prouve pas
sa qualité linguistique. Le verdict d’écoute reste ouvert. Le correctif a
permis une exécution réelle sous 16 Go ; le pré-audit documentaire seul ne
justifiait donc pas de conclure à l’impossibilité sur cette machine.

Code officiel de départ :
[`e1c935e81e356c87419d9509d7f8a4091457bdca`](https://github.com/Tencent-Hunyuan/AuK/tree/e1c935e81e356c87419d9509d7f8a4091457bdca),
avec le correctif explicite ci-dessus. Poids Flash :
[`575b92f0895f75180bf2cbd35f2e176c5732b8ed`](https://huggingface.co/tencent/AuK-Flash/tree/575b92f0895f75180bf2cbd35f2e176c5732b8ed).
Encodeur Qwen2.5-Omni-3B :
[`f75b40e3da2003cdd6e1829b1f420ca70797c34e`](https://huggingface.co/Qwen/Qwen2.5-Omni-3B/tree/f75b40e3da2003cdd6e1829b1f420ca70797c34e).
AuK déclare MIT ; l’encodeur conserve sa licence Qwen Research distincte.
Les quelque 18,7 Go de fichiers requis restent en cache sur C:, hors Git.
[Documentation AuK](https://github.com/Tencent-Hunyuan/AuK),
[fiche Flash](https://huggingface.co/tencent/AuK-Flash).

## IndexTTS

**IndexTTS : non testé.** La version officielle 2.5, publiée le 10 août 2026, annonce chinois, anglais, japonais, espagnol et arabe ; **le français n’est pas dans cette liste**. Son contrôle émotionnel ne suffit donc pas à le qualifier pour Ariane francophone. [Dépôt officiel IndexTTS](https://github.com/index-tts/index-tts).

## Présélection documentaire initiale

| Modèle | Français et jeu vocal | Mémoire et latence documentées | Licence et choix |
|---|---|---|---|
| **VoxCPM2, 2B**, avril 2026 | Français parmi 30 langues ; création d’une voix par description, sans référence. Description de l’émotion, du débit et du timbre. Une voix synthétique retenue peut ensuite servir de référence avec un style variable. Sortie 48 kHz. | Environ **8 Go VRAM** annoncés ; RTF ≈0,30 sur **RTX 4090**, ≈0,13 avec Nano-vLLM. Ces chiffres ne mesurent ni notre 4080, ni le délai du premier son ; nos mesures Windows figurent plus haut. | Code et poids **Apache-2.0**. Échantillons locaux disponibles, écoute à comparer à Qwen. [Dépôt officiel](https://github.com/OpenBMB/VoxCPM), [fiche des poids](https://huggingface.co/openbmb/VoxCPM2). |
| **Qwen3-TTS-12Hz-1.7B-VoiceDesign**, 22 janvier 2026 | Français parmi 10 langues ; texte + `instruct` pour créer une voix et diriger l’expression. Aucun échantillon humain nécessaire. Pour réutiliser un personnage, les auteurs proposent VoiceDesign puis Base avec la référence synthétique. | BF16 et FlashAttention 2 recommandés. Les **97 ms** annoncées pour la famille ne garantissent pas cette latence avec VoiceDesign/Python sur notre carte. Nos mesures locales figurent plus haut. | **Apache-2.0**. Voix de référence déjà approuvée ; profil Base créé. [Dépôt officiel](https://github.com/QwenLM/Qwen3-TTS), [poids VoiceDesign](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign). |
| **Fish Audio S2 Pro**, mars 2026 | Français classé « Tier 2 » par les auteurs. Contrôle local par balises libres, notamment colère, souffle et pauses ; pas uniquement une émotion globale. Une référence est facultative, avec timbre choisi aléatoirement en son absence. | Installation officielle : **24 Go VRAM**, Linux/WSL. RTF 0,195 et premier son ≈100 ms mesurés sur **H200**. Une exécution confortable sur 16 Go n’est pas établie par ces chiffres. | **Fish Audio Research License** : recherche/usage non commercial gratuit, accord distinct pour usage commercial. À garder après les deux essais adaptés au matériel. [Fiche et performances](https://huggingface.co/fishaudio/s2-pro), [installation](https://speech.fish.audio/install/), [inférence sans référence](https://github.com/fishaudio/fish-speech/blob/main/docs/en/inference.md), [licence](https://github.com/fishaudio/fish-speech/blob/main/LICENSE). |

RTF = temps de calcul / durée de l’audio. Un RTF inférieur à 1 ne suffit pas à prouver une première réponse rapide. Les chiffres de mémoire excluent toute garantie de coexistence avec ARDY : commencer par une génération vocale isolée, puis mesurer la charge simultanée.

## Environnements et provenance

Les premiers essais Qwen et Vox ont tourné sous **Windows natif**. VoxCPM dispose d’un environnement neuf `.local/voice-voxcpm-01/.venv`, Python 3.12.12, qui hérite en lecture des dépendances de l’environnement Qwen existant. Seul `voxcpm==2.0.3` y a été installé, sans modifier Qwen, ARDY ou le cœur de Promethee. Torch et torchaudio sont en 2.5.1+cu124 ; transformers en 4.57.3. Ce premier essai Vox utilise BF16, `load_denoiser=False`, **`optimize=False`**, sans compilation ni Nano-vLLM. Les autres environnements et les optimisations sont distingués dans leurs mesures respectives.

Les poids Vox épinglés ont été téléchargés publiquement sur C: dans `C:/Users/Cat6A/.cache/promethee/voxcpm2/32279effe8c19989596f05d353d1447f51d9e915` ; le téléchargement a pris 94,958 s. L’inférence a ensuite été exécutée hors ligne. `download.json` et `benchmark.json` conservent les chemins, versions et paramètres. Les prérequis officiels et versions de paquets sont disponibles dans [VoxCPM Quick Start](https://voxcpm.readthedocs.io/en/latest/quickstart.html), [VoxCPM PyPI](https://pypi.org/project/voxcpm/2.0.3/) et [Qwen PyPI](https://pypi.org/project/qwen-tts/0.1.1/).

Révisions des API publiques GitHub/Hugging Face, relevées le 16 septembre :

| Candidat | Code consulté, SHA Git | Poids, révision HF |
|---|---|---|
| VoxCPM2 | [`f772e498a45fbb5fb8e13fbf9b9c48be9fe33e69`](https://github.com/OpenBMB/VoxCPM/commit/f772e498a45fbb5fb8e13fbf9b9c48be9fe33e69), 2 septembre | [`openbmb/VoxCPM2@32279effe8c19989596f05d353d1447f51d9e915`](https://huggingface.co/openbmb/VoxCPM2/tree/32279effe8c19989596f05d353d1447f51d9e915) |
| Qwen VoiceDesign | [`022e286b98fbec7e1e916cb940cdf532cd9f488e`](https://github.com/QwenLM/Qwen3-TTS/commit/022e286b98fbec7e1e916cb940cdf532cd9f488e), 17 mars | [`Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign@5ecdb67327fd37bb2e042aab12ff7391903235d3`](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign/tree/5ecdb67327fd37bb2e042aab12ff7391903235d3) |
| Fish S2 Pro | [`befe4001745417f8c42131739d862b8a6fdbd15a`](https://github.com/fishaudio/fish-speech/commit/befe4001745417f8c42131739d862b8a6fdbd15a), 22 août | [`fishaudio/s2-pro@1de9996b6be38b745688de084d87a5633f714e4e`](https://huggingface.co/fishaudio/s2-pro/tree/1de9996b6be38b745688de084d87a5633f714e4e) |

Télécharger les poids avec `snapshot_download(repo_id, revision=SHA)`, puis charger le dossier obtenu. Fixer le paquet PyPI **ou** la révision Git pour le code, sans installer depuis une branche mobile. Aucun serveur supplémentaire n’est nécessaire au premier échantillon.

## Échantillon et limites de comparaison

Même texte pour les deux premiers candidats :

> Juste ! J'adore ce mot. Trois heures de boulot, et monsieur appelle ça une petite modification. Non mais... quelle journée !

Direction de voix utilisée par Qwen puis Vox :

> A young adult woman speaking native metropolitan French with a natural French accent. Warm clear feminine mid-register voice, slightly husky, intimate conversational delivery. She is angry and exasperated after a terrible day at work, with sharp sarcastic emphasis on 'Juste', expressive pitch variation, natural breaths and short dramatic pauses. Speak like an irritated person talking to a close friend, without shouting or singing.

Avec **VoxCPM2**, placer cette description entre parenthèses au début de `text`, comme dans son API officielle. Charger avec `load_denoiser=False`, puis commencer avec `cfg_value=2.0`, `inference_timesteps=10`, `retry_badcase=False`. Pour **voxcpm 2.0.3**, fixer `torch.manual_seed(42)` avant l’appel : sa wheel officielle vérifiée n’accepte pas l’argument `seed`, malgré l’exemple du README GitHub plus récent. Écrire le WAV à `model.tts_model.sample_rate`. Avec **Qwen**, appeler `generate_voice_design(text=..., language="French", instruct=...)` en BF16. Les fonctions et formats sont documentés dans les [exemples VoxCPM 2.0.3](https://pypi.org/project/voxcpm/2.0.3/) et [Qwen VoiceDesign](https://github.com/QwenLM/Qwen3-TTS#voice-design).

Le premier essai Vox utilise en plus la référence synthétique Qwen, sans cache de profil ; l’essai Vox WSL optimisé et Qwen Base réutilisent leur profil. Vox et le premier VoiceDesign partagent le texte complet, mais les six phrases du benchmark Base diffèrent : ce n’est pas un classement contrôlé de vitesse entre les modèles. L’écoute doit vérifier français, colère, pauses, mots conservés et stabilité de l’identité. Les deux appels Vox Windows ont réinitialisé la graine 42, mais leurs fichiers diffèrent : aucun déterminisme binaire général n’est affirmé.

Après sélection, générer les six répliques d’Ariane, vérifier la cohérence du timbre, puis recalculer leurs repères depuis le PCM final. Ne pas imposer aux nouvelles voix les durées de Hortense. Pour une identité stable avec styles variables, VoxCPM2 peut réutiliser **notre propre voix synthétique**, sans chercher une personne à cloner. Cette voix restitue les textes du même agent ; elle ne crée ni second cerveau, ni mémoire séparée, ni preuve d’un état émotionnel vécu.
