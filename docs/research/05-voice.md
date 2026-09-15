# Blocage 5 — voix réelle, interruption et cohérence

Recherche du 15 septembre 2026. Lecture du code, des qualifications locales et de la documentation officielle OpenAI actuelle. Aucun appel payant, installation, capture microphone ou changement du produit effectué.

## Conclusion

**Conserver GPT-Live avec délégation client vers Hermes est la voie la plus cohérente.** Ce n'est pas une intégration construite contre une API inexistante ou un ancien protocole Realtime : `gpt-live-1`, `/v1/live/sessions` et la délégation client sont documentés actuellement. La clé manquante empêche l'essai distant, mais elle ne corrige ni les interruptions ni les délais de la boucle applicative. [Présentation officielle](https://developers.openai.com/api/docs/guides/live)

Le minimum consiste à qualifier le transport existant avec une session réelle bornée. La cible navigateur peut ensuite utiliser **WebRTC Live**, sans changer de famille de modèle, avec Hermes gardé côté serveur. [WebRTC Live](https://developers.openai.com/api/docs/guides/voice-webrtc?api=live)

## État réellement établi

| Élément | Constat vérifié |
|---|---|
| Dépendances | Import local : `.local/openai-live-env` contient OpenAI **3.14.0**, websockets **15.0.1**, et expose `AsyncOpenAI.live`. L'environnement `.venv` Promethee conserve OpenAI **2.24.0**. Pas de raison de migrer Hermes pour débloquer Live. |
| Service | `live_worker.py:168` utilise `client.live.connect`, attend `session.started` et configure délégation `client`, PCM mono 24 kHz et `store: false`. Les essais décrits dans `docs/live-integration.md` utilisent le vrai SDK contre un serveur local simulé. |
| Accès | `PROMETHEE_OPENAI_API_KEY` est absente selon le diagnostic racine. L'authentification ChatGPT native utilisée par Hermes ne remplit pas cette variable ; l'accès au service vocal avec une clé de projet reste inconnu jusqu'à une connexion réelle. Ne pas confondre cela avec l'accès Hugging Face au modèle de mouvement. |
| Interruption | `live_session.py:187` ne vide la lecture qu'à réception d'un fragment de transcription utilisateur non vide. Le PCM suivant est écrit inconditionnellement au périphérique si la session n'est pas en fermeture (`:168`). Il peut donc réintroduire de la parole après la vidange. |
| Tours Hermes | `live_delegation.py:129` invalide un tour actif à chaque nouveau fragment utilisateur. La fenêtre de regroupement de 200 ms n'atteste pas la fin de phrase ; un acquiescement ou un fragment tardif peut interrompre un travail encore pertinent. |
| Audio matériel | `live_audio.py` emploie des blocs de 20 ms, une capture bornée à 500 ms et une file de lecture d'au plus une seconde. Aucun traitement d'écho ni détection acoustique de parole n'est installé dans ce code. Les périphériques et leur latence réelle restent non qualifiés. |
| Diagnostic STT/TTS | `voice_worker.py:47` utilise bien l'API TTS streaming, mais accumule tout le PCM avant de retourner le résultat. La lecture ne commence donc pas au premier fragment. |

Deux mesures de `.local/astra-live-delegation-01/report.json` valent **20,1036 s** et **19,9544 s**. Il s'agit de deux demandes de lecture/vérification du monde, avec vrai Astra mais événements Live simulés. Dans `qualify_live_delegation.py:66`, le chrono commence avant l'ingestion des fragments et s'arrête après `bridge.poll()` : il inclut le regroupement, le parcours Hermes/processus, l'appel et les outils, puis la remontée du résultat. **Ce n'est ni le temps d'inférence seul, ni une latence vocale, ni un benchmark représentatif de toutes les réponses Astra.**

## Trois options

| Option | Avantage pour Promethee | Travail et limite | Décision |
|---|---|---|---|
| **GPT-Live + Hermes, puis média WebRTC dans le navigateur** | Réutilise l'hôte, la mémoire et les outils existants ; le dialogue peut se poursuivre pendant le travail du backend. | Deux modèles distincts : Live gère les formulations et le dialogue, Astra les tâches déléguées. Cela ne signifie pas qu'Astra choisit mot pour mot toutes les phrases. Accès réel, interruption, cohérence et synchronisation restent à valider. | **Recommandé.** Qualifier d'abord le chemin WebSocket existant ; passer au média navigateur pour l'expérience finale. |
| **STT → même Hermes/Astra → TTS** | Un seul décideur textuel ; texte exact connu avant synthèse, contrôle de la provenance et des phrases plus simple. Le diagnostic existe déjà. | Cumule les étapes. Le code attend actuellement le TTS complet. Il faut lecture progressive, interruption locale, gestion des fragments et traitement du délai Hermes. | Repli utile pour une première parole reproductible ; ne pas promettre une conversation spontanée à partir du diagnostic actuel. |
| **Realtime comme voix et cerveau principal** | Un modèle audio prend en charge parole, raisonnement et outils ; le protocole Realtime fournit une gestion d'interruption liée au VAD. | Transférer l'autorité de décision ou reconnecter Hermes comme outil impose un changement d'architecture. Ne préserve pas à lui seul « Astra est le cerveau ». | Ne pas migrer seulement parce que Realtime est plus connu ; option de comparaison si les essais Live échouent. |

Cette distinction entre Live, Realtime et chaîne STT/agent/TTS est explicitement documentée. [Comparaison officielle](https://developers.openai.com/api/docs/guides/voice-agents)

Pour le repli, les noms actuels correspondant au code sont `gpt-transcribe` pour un enregistrement borné et `gpt-4o-mini-tts` pour synthétiser la réponse. Le premier produit une transcription de fichier ; ce n'est pas la même chose qu'un flux microphone continu. Le TTS permet de lire avant réception du fichier complet, capacité à exposer dans notre processus. [Transcription](https://developers.openai.com/api/docs/guides/speech-to-text), [TTS](https://developers.openai.com/api/docs/guides/text-to-speech)

## Changements minimaux proposés

1. **Qualification d'accès de 30–60 secondes**, avec la clé configurée localement, la voix et le modèle prévus. Vérifier démarrage, vraie réponse française, fermeture `session.closed` et bilan d'usage. Ne pas commencer par un appel complet impliquant mouvement et mémoire : isoler d'abord la voix.
2. **Séparer interruption sonore et correction de tâche.** Un signal acoustique peut couper la sortie immédiatement ; seule une correction pertinente doit invalider une action en cours. Préserver les identifiants de tour et les protections existantes contre les résultats tardifs. Ne plus assimiler systématiquement tout fragment à une nouvelle intention.
3. **Définir une politique de reprise audio testable.** Maintenir un état de lecture coupée, vider les buffers, supprimer les fragments pendant la coupure et reprendre selon une règle explicite. Live n'offre pas les mêmes événements d'annulation/troncature que Realtime : ne pas inventer de `response.cancel` Live. La documentation recommande un contrôle de sortie client et une instruction corrective ; l'accusé de cette instruction n'autorise pas à lui seul la reprise. [Contrôle de lecture Live](https://developers.openai.com/api/docs/guides/voice-server-controls?api=live)
4. **Mesurer avant d'optimiser Hermes.** Ajouter des horodatages distincts : parole entrante, délégation, démarrage backend, premier résultat utile, résultat final, arrivée audio, rendu audio. Tester réutilisation de processus/connexion et transmission de résultats vérifiés partiels si le contrat Hermes le permet. Une phrase de remplissage immédiate ne doit pas être comptée comme une réponse utile.
5. **Un seul propriétaire du son et de son horloge.** Faire partir lecture, capture vidéo et analyse des lèvres du même flux réellement rendu. Pour WebRTC, utiliser la piste reçue côté navigateur ; garder la connexion latérale pour le contrôle. Ne pas utiliser les horodatages de transcription comme alignement phonétique ou preuve d'audition : ils n'ont pas cette précision. [Temps des transcriptions](https://developers.openai.com/api/docs/guides/live-conversations)

La bascule vers WebRTC exige un endpoint serveur qui crée la session Live à partir de l'offre SDP ; la clé reste côté serveur. La session est déjà démarrée par HTTP : pas de deuxième `session.start` sur le canal de données. Choisir un unique propriétaire des délégations afin que le navigateur et la connexion latérale ne déclenchent pas deux fois Hermes. Ce changement simplifie le raccord à l'avatar navigateur, mais n'est pas une preuve que l'écho ou les interruptions seront corrects sur la machine cible.

## Critères d'essai proposés

Ces seuils sont des objectifs de produit à mesurer, pas des performances garanties du fournisseur.

- Vingt échanges français variés, puis une conversation libre continue de deux minutes ; tester questions simples, réflexion longue, chiffres, silences et reprise.
- Au moins dix interruptions pendant la lecture et dix corrections pendant un appel Hermes : aucune ancienne action déclenchée tardivement, aucune ancienne phrase réintroduite après la reprise.
- Mesurer la coupure acoustique réelle ; cible initiale médiane ≤ 200 ms, p95 ≤ 400 ms. Distinguer l'instant où le logiciel vide sa file de celui où le son s'arrête au périphérique.
- Pour les échanges simples, cible de première réponse utile ≤ 1 s médiane et ≤ 2 s p95 ; rapporter séparément les tâches qui nécessitent un appel backend. Si non atteint, conserver le résultat et l'origine du délai.
- Vérifier les lèvres et la parole avec une capture commune, y compris après interruption : pas de lèvres animées par un audio rejeté. Cible initiale d'écart perceptible ≤ 80 ms à confirmer à l'écoute et au visionnage.
- Vérifier que tout succès annoncé correspond à une exécution enregistrée. Après redémarrage, aucun rejeu d'action ou de son ; mémoire cohérente avec les éléments effectivement connus.

## Coût et limite de cette recherche

Au 15 septembre 2026, la page officielle de `gpt-live-1` indique **0,05 USD par minute de session, facturation à la seconde**, hors backend et outils. Cela représente 3 USD pour une heure de session continue avant le backend ; ce calcul n'est pas un prix total de l'avatar. L'accès du compte et le coût réellement facturé n'ont pas été testés. [Tarification du modèle](https://developers.openai.com/api/docs/models/gpt-live-1)

La recherche montre une voie concrète sans nouveau modèle local ni remplacement de Hermes. Elle ne résout pas les quatre autres blocages corporels : la voix peut être convaincante alors que le corps reste rigide. Leur synchronisation doit faire l'objet d'un essai commun après qualification séparée.
