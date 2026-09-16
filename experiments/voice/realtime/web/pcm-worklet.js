/* Pull-driven mono PCM playback. Audio time, not HTTP arrivals, owns played_frames. */
class ArianePCM extends AudioWorkletProcessor {
    constructor() {
        super();
        this.epoch = 0;
        this.queue = [];
        this.played = 0;
        this.underflows = 0;
        this.framesToReport = 0;
        this.energyToReport = 0;
        this.prebuffer = Math.round(sampleRate * 0.5);
        this.port.onmessage = ({ data }) => this.receive(data);
    }
    receive(data) {
        if (data.type === "reset") {
            this.epoch = data.epoch;
            this.queue = [];
            this.played = 0;
            this.underflows = 0;
            this.framesToReport = 0;
            this.energyToReport = 0;
            this.report(0);
            return;
        }
        if (data.epoch !== this.epoch) return;
        if (data.type === "begin") {
            if (!this.queue.some((x) => x.id === data.id))
                this.queue.push({
                    id: data.id,
                    chunks: [],
                    offset: 0,
                    available: 0,
                    ended: false,
                    started: false,
                    starved: false,
                });
            return;
        }
        const item = this.queue.find((x) => x.id === data.id);
        if (!item) return;
        if (data.type === "pcm") {
            item.chunks.push(data.pcm);
            item.available += data.pcm.length;
        }
        if (data.type === "end") item.ended = true;
    }
    report(rms) {
        this.port.postMessage({
            type: "stats",
            epoch: this.epoch,
            played_frames: this.played,
            underflows: this.underflows,
            buffered_frames: this.queue.reduce((n, x) => n + x.available, 0),
            rms,
        });
    }
    process(inputs, outputs) {
        const out = outputs[0][0];
        out.fill(0);
        let energy = 0;
        for (let i = 0; i < out.length; i++) {
            let item = this.queue[0];
            while (item && item.ended && item.available === 0) {
                this.queue.shift();
                this.report(0);
                this.port.postMessage({
                    type: "finished",
                    epoch: this.epoch,
                    id: item.id,
                });
                item = this.queue[0];
            }
            if (!item) break;
            if (!item.started) {
                if (
                    item.available >= this.prebuffer ||
                    (item.ended && item.available > 0)
                ) {
                    item.started = true;
                    this.port.postMessage({
                        type: "playing",
                        epoch: this.epoch,
                        id: item.id,
                    });
                } else break;
            }
            if (!item.available) {
                if (!item.starved) {
                    item.starved = true;
                    this.underflows++;
                }
                break;
            }
            item.starved = false;
            const chunk = item.chunks[0];
            const value = chunk[item.offset++];
            out[i] = value;
            energy += value * value;
            item.available--;
            this.played++;
            if (item.offset === chunk.length) {
                item.chunks.shift();
                item.offset = 0;
            }
        }
        this.framesToReport += out.length;
        this.energyToReport += energy;
        if (this.framesToReport >= sampleRate / 30) {
            this.report(Math.sqrt(this.energyToReport / this.framesToReport));
            this.framesToReport = 0;
            this.energyToReport = 0;
        }
        return true;
    }
}
registerProcessor("ariane-pcm", ArianePCM);
