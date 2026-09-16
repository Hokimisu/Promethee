export const INPUT_SAMPLE_RATE = 16000;
export const MAX_INPUT_SAMPLES = 12 * INPUT_SAMPLE_RATE;
export const PRE_SPEECH_PAD_MS = 800;
// Preserve the onset preceding detection; this does not reduce detection delay.
// 11.1 s after speech-start + 0.8 s retained audio leave a frame-size margin.
export const CAPTURE_TIMEOUT_MS = 11100;

export function pcm16Base64(audio) {
    if (!(audio instanceof Float32Array) || !audio.length)
        throw new Error("La capture audio est vide.");
    const length = Math.min(audio.length, MAX_INPUT_SAMPLES);
    const bytes = new Uint8Array(length * 2);
    const view = new DataView(bytes.buffer);
    for (let i = 0; i < length; i++) {
        if (!Number.isFinite(audio[i]))
            throw new Error(
                "La capture audio contient un échantillon invalide.",
            );
        const value = Math.max(-1, Math.min(1, audio[i]));
        view.setInt16(
            i * 2,
            Math.round(value * (value < 0 ? 32768 : 32767)),
            true,
        );
    }
    let binary = "";
    for (let i = 0; i < bytes.length; i += 8192)
        binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
    return btoa(binary);
}

function errorMessage(error) {
    if (error?.name === "NotAllowedError")
        return "Accès au micro refusé. Vous pouvez continuer à écrire.";
    if (error?.name === "NotFoundError")
        return "Aucun microphone disponible. Vous pouvez continuer à écrire.";
    return error?.message ?? "Le microphone est indisponible.";
}

function stopTracks(stream) {
    stream?.getTracks().forEach((track) => track.stop());
}

/** Local capture lifecycle. All browser/network dependencies are injectable. */
export class MicrophoneInput {
    constructor({
        createContext,
        getUserMedia,
        createDetector,
        request,
        interrupt,
        adoptSession,
        allowAudio,
        canListen = () => true,
        onState = () => {},
        makeId = () => `input-${crypto.randomUUID()}`,
        setTimer = (callback, delay) => globalThis.setTimeout(callback, delay),
        clearTimer = (timer) => globalThis.clearTimeout(timer),
    }) {
        Object.assign(this, {
            createContext,
            getUserMedia,
            createDetector,
            request,
            interrupt,
            adoptSession,
            allowAudio,
            canListen,
            onState,
            makeId,
            setTimer,
            clearTimer,
        });
        this.enabled = false;
        this.phase = "off";
        this.error = null;
        this.resource = null;
        this.capture = null;
    }
    get waitingForStart() {
        return Boolean(this.capture && !this.capture.session);
    }
    get busy() {
        return Boolean(this.capture && !this.capture.submitted);
    }
    snapshot() {
        return {
            enabled: this.enabled,
            phase: this.phase,
            error: this.error,
            input_id: this.capture?.id ?? null,
        };
    }
    update(phase = this.phase) {
        this.phase = phase;
        this.onState(this.snapshot());
    }
    live(resource) {
        return this.enabled && this.resource === resource;
    }
    async enable() {
        if (this.enabled) return;
        this.enabled = true;
        this.error = null;
        const resource = {};
        this.resource = resource;
        this.update("opening");
        try {
            // Called directly from the activation click, before the first await.
            resource.context = this.createContext();
            const resume = resource.context.resume();
            const streamReady = this.getUserMedia({
                audio: {
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                },
            }).then((stream) => {
                resource.stream = stream;
                if (!this.live(resource)) stopTracks(stream);
                return stream;
            });
            await Promise.all([resume, streamReady]);
            if (!this.live(resource)) return;
            for (const track of resource.stream.getTracks())
                track.addEventListener?.(
                    "ended",
                    () => {
                        if (this.live(resource))
                            this.fail(
                                new Error("Le microphone a été déconnecté."),
                            );
                    },
                    { once: true },
                );
            resource.detector = await this.createDetector({
                context: resource.context,
                stream: resource.stream,
                onSpeechStart: () => {
                    if (this.live(resource)) this.speechStart();
                },
                onSpeechEnd: (pcm) => {
                    if (this.live(resource)) void this.speechEnd(pcm);
                },
                onMisfire: () => {
                    if (this.live(resource)) this.cancelInput();
                },
                onError: (error) => {
                    if (this.live(resource)) this.fail(error);
                },
            });
            if (!this.live(resource)) {
                await resource.detector.destroy();
                return;
            }
            await resource.detector.start();
            if (this.live(resource) && !this.capture) this.update("ready");
        } catch (error) {
            if (this.live(resource)) this.fail(error);
        }
    }
    fail(error) {
        this.error = errorMessage(error);
        this.disable();
        this.update("failed");
    }
    disable() {
        this.enabled = false;
        const resource = this.resource;
        this.resource = null;
        try {
            this.cancelInput(false);
        } catch (error) {
            this.error ??= errorMessage(error);
        } finally {
            // Local capture must stop even if cancellation or its timer throws.
            stopTracks(resource?.stream);
            void resource?.context?.close().catch(() => {});
            void resource?.detector?.destroy().catch(() => {});
            this.update("off");
        }
    }
    cancelRemote(capture) {
        if (!capture.session || capture.cancelSent) return;
        capture.cancelSent = true;
        void this.request("/input_cancel", {
            input_id: capture.id,
            session_id: capture.session,
        }).catch(() => {});
    }
    cancelInput(resetDetector = true) {
        const old = this.capture;
        this.capture = null;
        if (old) {
            try {
                this.clearTimer(old.timer);
            } finally {
                this.cancelRemote(old);
            }
        }
        const resource = this.resource;
        if (resetDetector && old && !old.ended)
            void resource?.detector?.discardSegment().catch((error) => {
                if (this.live(resource)) this.fail(error);
            });
        this.update(this.enabled ? "ready" : "off");
    }
    speechStart() {
        if (!this.enabled || !this.canListen()) return;
        const old = this.capture;
        this.capture = null;
        if (old) {
            this.clearTimer(old.timer);
            this.cancelRemote(old);
        }
        // This must mute playback and advance the app fence synchronously.
        const epoch = this.interrupt();
        const capture = {
            id: this.makeId(),
            epoch,
            session: null,
            ended: false,
            submitted: false,
            cancelSent: false,
        };
        this.capture = capture;
        this.error = null;
        this.update("listening");
        const resource = this.resource;
        capture.timer = this.setTimer(() => {
            if (this.capture === capture && !capture.ended)
                void resource?.detector?.finishSegment().catch((error) => {
                    if (this.live(resource) && this.capture === capture)
                        this.fail(error);
                });
        }, CAPTURE_TIMEOUT_MS);
        capture.start = this.request("/input_start", { input_id: capture.id })
            .then((result) => {
                if (
                    typeof result.session_id !== "string" ||
                    !result.session_id ||
                    !Number.isSafeInteger(result.cursor) ||
                    result.cursor < 0 ||
                    result.input_id !== capture.id
                )
                    throw new Error("Réponse d’écoute invalide.");
                capture.session = result.session_id;
                if (this.capture !== capture || !this.enabled) {
                    this.cancelRemote(capture);
                    return false;
                }
                if (!this.adoptSession(result, epoch)) {
                    this.cancelRemote(capture);
                    this.cancelInput(false);
                    return false;
                }
                return true;
            })
            .catch((error) => {
                if (this.capture === capture) {
                    this.error = errorMessage(error);
                    this.cancelInput();
                    this.update("failed");
                }
                return false;
            });
    }
    async speechEnd(pcm) {
        const capture = this.capture;
        if (!capture || capture.ended) return;
        capture.ended = true;
        this.clearTimer(capture.timer);
        this.update("transcribing");
        try {
            const encoded = pcm16Base64(pcm);
            if (
                !(await capture.start) ||
                this.capture !== capture ||
                !this.enabled
            )
                return;
            const result = await this.request("/input_audio", {
                input_id: capture.id,
                session_id: capture.session,
                sample_rate: INPUT_SAMPLE_RATE,
                pcm16: encoded,
            });
            if (this.capture !== capture || !this.enabled) return;
            if (
                result.session_id !== capture.session ||
                result.input_id !== capture.id
            )
                throw new Error("Réponse de transcription invalide.");
            // Never enable playback before the audio upload was accepted.
            if (!this.allowAudio(capture.session, capture.epoch)) {
                this.cancelInput(false);
                return;
            }
            capture.submitted = true;
            this.update("transcribing");
        } catch (error) {
            if (this.capture === capture) {
                this.error = errorMessage(error);
                this.cancelInput(false);
                this.update("failed");
            }
        }
    }
    observe(input) {
        if (!this.capture || input?.input_id !== this.capture.id) return;
        if (input.state === "completed" && !this.capture.submitted) return;
        if (input.state === "completed") {
            // The server already handed the transcript to Hermes. Closing the
            // local capture must not ask it to cancel that completed input.
            this.capture = null;
            this.update("ready");
        } else if (["failed", "cancelled"].includes(input.state)) {
            this.cancelInput();
            if (input.state === "failed")
                this.error = input.error ?? "La transcription a échoué.";
            this.update(input.state === "failed" ? "failed" : "ready");
        }
    }
}
