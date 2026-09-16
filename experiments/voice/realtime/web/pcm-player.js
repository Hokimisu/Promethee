export class PCMPlayer {
    constructor({
        onStats = () => {},
        onSpeech = () => {},
        onPlayback = () => {},
    } = {}) {
        this.onStats = onStats;
        this.onSpeech = onSpeech;
        this.onPlayback = onPlayback;
        this.epoch = 0;
        this.session = null;
        this.items = new Map();
        this.seen = new Set();
        this.playing = null;
        this.stats = {
            played_frames: 0,
            underflows: 0,
            buffered_frames: 0,
            rms: 0,
        };
        this.received = 0;
        this.ready = null;
        this.statsAt = -Infinity;
    }
    async enable() {
        if (!this.context) {
            this.context = new AudioContext({
                sampleRate: 48000,
                latencyHint: "interactive",
            });
            this.gain = this.context.createGain();
            this.gain.gain.value = 0;
            this.gain.connect(this.context.destination);
            this.ready = this.context.audioWorklet
                .addModule("/pcm-worklet.js")
                .then(() => {
                    this.node = new AudioWorkletNode(
                        this.context,
                        "ariane-pcm",
                        {
                            numberOfInputs: 0,
                            numberOfOutputs: 1,
                            outputChannelCount: [1],
                        },
                    );
                    this.node.connect(this.gain);
                    this.node.port.onmessage = ({ data }) => {
                        if (data.epoch !== this.epoch) return;
                        if (data.type === "stats") {
                            this.stats = data;
                            this.statsAt = performance.now();
                            this.onStats(data);
                        }
                        if (data.type === "playing") {
                            this.playing = data.id;
                            this.onSpeech(this.items.get(data.id)?.text ?? "");
                            this.onPlayback(
                                "playback_started",
                                this.session,
                                data.id,
                                this.stats,
                            );
                        }
                        if (data.type === "finished") {
                            if (this.playing === data.id) {
                                this.onPlayback(
                                    "playback_finished",
                                    this.session,
                                    data.id,
                                    this.stats,
                                );
                                this.playing = null;
                            }
                            this.items.delete(data.id);
                            this.onSpeech("");
                        }
                    };
                });
        }
        await Promise.all([this.ready, this.context.resume()]);
        if (this.context.sampleRate !== 48000)
            throw new Error("La sortie audio 48 kHz est indisponible.");
    }
    reset(session = null) {
        const started = performance.now();
        this.epoch++;
        if (this.gain) {
            this.gain.gain.cancelScheduledValues(this.context.currentTime);
            this.gain.gain.setValueAtTime(0, this.context.currentTime);
        }
        if (this.playing)
            this.onPlayback(
                "playback_interrupted",
                this.session,
                this.playing,
                this.stats,
            );
        this.playing = null;
        this.session = session;
        this.items.clear();
        this.seen.clear();
        this.received = 0;
        this.statsAt = -Infinity;
        this.node?.port.postMessage({ type: "reset", epoch: this.epoch });
        this.stats = {
            played_frames: 0,
            underflows: 0,
            buffered_frames: 0,
            rms: 0,
        };
        this.onStats(this.stats);
        this.onSpeech("");
        return performance.now() - started;
    }
    get renderedRms() {
        return this.playing &&
            this.context?.state === "running" &&
            this.gain?.gain.value > 0 &&
            performance.now() - this.statsAt < 150
            ? this.stats.rms
            : 0;
    }
    accept(event) {
        if (!this.node || !this.session || event.session_id !== this.session)
            return;
        if (event.event === "stop") {
            if (!event.id || this.items.has(event.id)) this.reset(this.session);
            return;
        }
        if (typeof event.id !== "string" || event.id.length > 300) return;
        if (event.event === "speech_start") {
            if (this.seen.has(event.id)) return;
            this.seen.add(event.id);
            if (this.items.size >= 40)
                throw new Error("Trop de répliques en attente.");
            this.items.set(event.id, {
                text: String(event.text ?? "").slice(0, 16000),
                seq: null,
                ended: false,
            });
            this.node.port.postMessage({
                type: "begin",
                epoch: this.epoch,
                id: event.id,
            });
            return;
        }
        const item = this.items.get(event.id);
        if (!item) return;
        if (event.event === "speech_end") {
            if (!item.ended) {
                item.ended = true;
                this.node.port.postMessage({
                    type: "end",
                    epoch: this.epoch,
                    id: event.id,
                });
            }
            return;
        }
        if (event.event !== "pcm" || item.ended) return;
        if (!Number.isInteger(event.seq) || event.seq < 0)
            throw new Error("Fragment audio invalide.");
        if (item.seq !== null && event.seq <= item.seq) return;
        if (
            (item.seq !== null && event.seq !== item.seq + 1) ||
            (item.seq === null && event.seq > 1)
        )
            throw new Error("Un fragment audio manque.");
        if (
            event.sample_rate !== 48000 ||
            !Number.isInteger(event.samples) ||
            event.samples <= 0 ||
            event.samples > 48000 * 30 ||
            typeof event.pcm_f32_b64 !== "string" ||
            event.pcm_f32_b64.length > 48000 * 30 * 6
        )
            throw new Error("Format audio invalide.");
        const raw = atob(event.pcm_f32_b64);
        if (raw.length !== event.samples * 4)
            throw new Error("Fragment audio incomplet.");
        const bytes = new Uint8Array(raw.length);
        for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
        const view = new DataView(bytes.buffer),
            pcm = new Float32Array(event.samples);
        for (let i = 0; i < pcm.length; i++) {
            pcm[i] = view.getFloat32(i * 4, true);
            if (!Number.isFinite(pcm[i]))
                throw new Error("Signal audio invalide.");
        }
        this.received += pcm.length;
        if (this.received - this.stats.played_frames > 48000 * 90)
            throw new Error("File audio trop longue.");
        item.seq = event.seq;
        this.gain.gain.setValueAtTime(1, this.context.currentTime);
        this.node.port.postMessage(
            { type: "pcm", epoch: this.epoch, id: event.id, pcm },
            [pcm.buffer],
        );
    }
}
