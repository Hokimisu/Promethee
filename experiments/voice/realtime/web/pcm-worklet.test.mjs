import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { AudioMouth } from "./audio-mouth.mjs";
function make() {
    let Processor;
    const sandbox = {
        sampleRate: 48000,
        AudioWorkletProcessor: class {
            constructor() {
                this.messages = [];
                this.port = { postMessage: (data) => this.messages.push(data) };
            }
        },
        registerProcessor: (name, cls) => {
            Processor = cls;
        },
    };
    vm.runInNewContext(
        readFileSync(new URL("./pcm-worklet.js", import.meta.url), "utf8"),
        sandbox,
    );
    const p = new Processor();
    p.receive({ type: "reset", epoch: 1 });
    return p;
}
function send(p, type, extra = {}) {
    p.receive({ type, epoch: 1, id: "a", ...extra });
}
function render(p, n = 128) {
    const out = new Float32Array(n);
    p.process([], [[out]]);
    return out;
}
test("prebuffer is 0.5 seconds; only rendered frames are counted", () => {
    const p = make();
    send(p, "begin");
    send(p, "pcm", { pcm: new Float32Array(23999).fill(0.25) });
    assert.equal(
        render(p).every((v) => v === 0),
        true,
    );
    assert.equal(p.played, 0);
    send(p, "pcm", { pcm: new Float32Array(1).fill(0.25) });
    assert.equal(
        render(p).every((v) => v === 0.25),
        true,
    );
    assert.equal(p.played, 128);
});
test("short completed utterance drains without waiting forever for prebuffer", () => {
    const p = make();
    send(p, "begin");
    send(p, "pcm", { pcm: new Float32Array(40).fill(0.5) });
    send(p, "end");
    const out = render(p);
    assert.equal(
        out.slice(0, 40).every((v) => v === 0.5),
        true,
    );
    assert.equal(
        out.slice(40).every((v) => v === 0),
        true,
    );
    assert.equal(p.played, 40);
    assert.equal(p.underflows, 0);
    assert.equal(p.messages.filter((m) => m.type === "finished").length, 1);
});
test("generation end drains remaining audio before announcing playback finished", () => {
    const p = make();
    send(p, "begin");
    send(p, "pcm", { pcm: new Float32Array(512).fill(0.2) });
    send(p, "end");
    render(p);
    assert.equal(
        p.messages.some((m) => m.type === "finished"),
        false,
    );
    for (let i = 0; i < 4; i++) render(p);
    assert.equal(p.played, 512);
    assert.equal(p.messages.filter((m) => m.type === "finished").length, 1);
    const lastStats = p.messages.filter((m) => m.type === "stats").at(-1);
    assert.equal(lastStats.played_frames, 512);
});
test("reset fences queued and late samples from the previous epoch", () => {
    const p = make();
    send(p, "begin");
    send(p, "pcm", { pcm: new Float32Array(24000).fill(0.8) });
    p.receive({ type: "reset", epoch: 2 });
    send(p, "pcm", { pcm: new Float32Array(24000).fill(0.8) });
    send(p, "begin");
    assert.equal(
        render(p).every((v) => v === 0),
        true,
    );
    assert.equal(p.played, 0);
    assert.equal(p.queue.length, 0);
});
test("one starvation episode is one underflow; resume uses new samples", () => {
    const p = make();
    send(p, "begin");
    send(p, "pcm", { pcm: new Float32Array(24000).fill(0.1) });
    for (let i = 0; i < 200; i++) render(p);
    assert.equal(p.played, 24000);
    assert.equal(p.underflows, 1);
    send(p, "pcm", { pcm: new Float32Array(80).fill(0.3) });
    send(p, "end");
    render(p);
    assert.equal(p.played, 24080);
    assert.equal(p.underflows, 1);
});
test("a later utterance queues after the first; it cannot discard its tail", () => {
    const p = make();
    send(p, "begin");
    send(p, "pcm", { pcm: new Float32Array(80).fill(0.25) });
    send(p, "end");
    send(p, "begin", { id: "b" });
    send(p, "pcm", { id: "b", pcm: new Float32Array(80).fill(0.5) });
    send(p, "end", { id: "b" });
    const first = render(p);
    assert.equal(
        first.slice(0, 80).every((v) => v === 0.25),
        true,
    );
    assert.equal(
        first.slice(80).every((v) => v === 0.5),
        true,
    );
    render(p);
    assert.equal(p.played, 160);
    assert.deepEqual(
        p.messages.filter((m) => m.type === "playing").map((m) => m.id),
        ["a", "b"],
    );
    assert.equal(p.underflows, 0);
});

test("mouth RMS includes all rendered samples, not only the last quiet quantum", () => {
    const p = make();
    send(p, "begin");
    const pcm = new Float32Array(24000);
    pcm.fill(0.3, 0, 128 * 12);
    send(p, "pcm", { pcm });
    for (let i = 0; i < 13; i++) render(p);
    const stats = p.messages.filter((m) => m.type === "stats").at(-1);
    assert.ok(Math.abs(stats.rms - 0.3 * Math.sqrt(12 / 13)) < 1e-6);
    for (let i = 0; i < 13; i++) render(p);
    assert.equal(p.messages.filter((m) => m.type === "stats").at(-1).rms, 0);
});

test("buffering and reset report silence even when future PCM contains speech", () => {
    const p = make();
    send(p, "begin");
    send(p, "pcm", { pcm: new Float32Array(23999).fill(0.6) });
    for (let i = 0; i < 13; i++) render(p);
    assert.equal(p.messages.filter((m) => m.type === "stats").at(-1).rms, 0);
    send(p, "pcm", { pcm: new Float32Array(1).fill(0.6) });
    render(p);
    p.receive({ type: "reset", epoch: 2 });
    for (let i = 0; i < 13; i++) render(p);
    assert.equal(p.messages.filter((m) => m.type === "stats").at(-1).rms, 0);
});

test(
    "configured Vox speech produces changing mouth weights from rendered PCM",
    { skip: !process.env.PROMETHEE_TEST_VOICE },
    () => {
        const wav = readFileSync(process.env.PROMETHEE_TEST_VOICE);
        let pcm;
        for (let at = 12; at + 8 <= wav.length;) {
            const kind = wav.toString("ascii", at, at + 4),
                length = wav.readUInt32LE(at + 4);
            if (kind === "fmt ") {
                assert.equal(wav.readUInt16LE(at + 8), 1);
                assert.equal(wav.readUInt16LE(at + 10), 1);
                assert.equal(wav.readUInt32LE(at + 12), 48000);
                assert.equal(wav.readUInt16LE(at + 22), 16);
            }
            if (kind === "data") {
                pcm = new Float32Array(length / 2);
                for (let i = 0; i < pcm.length; i++)
                    pcm[i] = wav.readInt16LE(at + 8 + i * 2) / 32768;
            }
            at += 8 + length + (length % 2);
        }
        assert.ok(pcm?.length > 48000);
        const p = make();
        send(p, "begin");
        send(p, "pcm", { pcm });
        send(p, "end");
        const mouth = new AudioMouth({
            getExpression: (name) => name === "aa",
            setValue() {},
        });
        const weights = [];
        while (p.queue.length) {
            render(p);
            const rms =
                p.messages.filter((m) => m.type === "stats").at(-1)?.rms ?? 0;
            weights.push(mouth.update(rms, 128 / 48000));
        }
        mouth.reset();
        assert.equal(p.played, pcm.length);
        assert.equal(p.underflows, 0);
        assert.ok(weights.some((value) => value > 0.6));
        assert.ok(weights.some((value) => value < 0.05));
        assert.equal(mouth.value, 0);
        const ordered = weights.toSorted((a, b) => a - b);
        console.log(
            JSON.stringify({
                archived_vox_seconds: pcm.length / 48000,
                mouth_median: ordered[Math.floor(ordered.length / 2)],
                mouth_p95: ordered[Math.floor(ordered.length * 0.95)],
            }),
        );
    },
);
