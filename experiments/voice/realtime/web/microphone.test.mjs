// CPU lifecycle tests with explicit browser/network doubles; no microphone/model.
import test from "node:test";
import assert from "node:assert/strict";
import {
    MicrophoneInput,
    pcm16Base64,
    MAX_INPUT_SAMPLES,
    CAPTURE_TIMEOUT_MS,
} from "./microphone.mjs";

function deferred() {
    let resolve, reject;
    const promise = new Promise((yes, no) => {
        resolve = yes;
        reject = no;
    });
    return { promise, resolve, reject };
}
const flush = async () => {
    for (let i = 0; i < 10; i++) await Promise.resolve();
};
function harness(overrides = {}) {
    const log = [],
        timers = new Map(),
        posts = [],
        detectors = [],
        contexts = [];
    let serial = 0,
        epoch = 0,
        session = null,
        armed = false,
        constraints;
    const tracks = [0, 1].map(() => ({
        stops: 0,
        stop() {
            this.stops++;
        },
        addEventListener(_, callback) {
            this.ended = callback;
        },
    }));
    const stream = { getTracks: () => tracks };
    const h = {
        log,
        timers,
        posts,
        detectors,
        contexts,
        tracks,
        stream,
        get armed() {
            return armed;
        },
        get constraints() {
            return constraints;
        },
        invalidate() {
            epoch++;
            armed = false;
        },
        ack(post, sid = "session-1") {
            post.result.resolve({
                session_id: sid,
                cursor: 12,
                input_id: post.body.input_id,
            });
        },
        latest(path) {
            return posts.filter((post) => post.path === path).at(-1);
        },
    };
    h.mic = new MicrophoneInput({
        createContext: () => {
            const context = {
                closes: 0,
                resume: async () => {},
                close() {
                    this.closes++;
                    return Promise.resolve();
                },
            };
            contexts.push(context);
            return context;
        },
        getUserMedia: async (value) => {
            constraints = value;
            return stream;
        },
        createDetector: async (callbacks) => {
            const detector = {
                callbacks,
                starts: 0,
                destroys: 0,
                discards: 0,
                async start() {
                    this.starts++;
                },
                async destroy() {
                    this.destroys++;
                },
                async discardSegment() {
                    this.discards++;
                },
                async finishSegment() {
                    callbacks.onSpeechEnd(
                        new Float32Array(MAX_INPUT_SAMPLES + 100).fill(0.2),
                    );
                },
            };
            detectors.push(detector);
            return detector;
        },
        request: (path, body) => {
            const result = deferred();
            const post = { path, body, result };
            log.push(path);
            posts.push(post);
            if (path === "/input_cancel") result.resolve({ ok: true });
            return result.promise;
        },
        interrupt: () => {
            log.push("mute");
            armed = false;
            return ++epoch;
        },
        adoptSession: (value, expected) => {
            if (expected !== epoch) return false;
            session = value.session_id;
            log.push("adopt");
            return true;
        },
        allowAudio: (sid, expected) => {
            if (sid !== session || expected !== epoch) return false;
            log.push("arm");
            armed = true;
            return true;
        },
        makeId: () => `input-${++serial}`,
        setTimer: (callback, ms) => {
            const id = ++serial;
            timers.set(id, { callback, ms });
            return id;
        },
        clearTimer: (id) => timers.delete(id),
        ...overrides,
    });
    h.begin = () => {
        h.detectors.at(-1).callbacks.onSpeechStart();
        return h.latest("/input_start");
    };
    h.end = (pcm = new Float32Array(3200).fill(0.25)) =>
        h.detectors.at(-1).callbacks.onSpeechEnd(pcm);
    return h;
}

test("no browser capture or context before explicit enable; AEC and noise suppression requested", async () => {
    const h = harness();
    assert.equal(h.contexts.length, 0);
    assert.equal(h.detectors.length, 0);
    await h.mic.enable();
    assert.equal(h.mic.phase, "ready");
    assert.deepEqual(h.constraints.audio, {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
    });
    h.mic.disable();
    assert.ok(h.tracks.every((track) => track.stops === 1));
    assert.equal(h.contexts[0].closes, 1);
});

test("default timer wrappers preserve the browser global receiver", async (t) => {
    const calls = [];
    // Web IDL timers reject this=MicrophoneInput. Plain arrow doubles cannot
    // reveal that browser-only failure, so exercise the actual defaults here.
    t.mock.method(globalThis, "setTimeout", function (callback, delay) {
        assert.equal(
            this,
            globalThis,
            "setTimeout requires the browser global",
        );
        assert.equal(typeof callback, "function");
        calls.push(["set", delay]);
        return 71;
    });
    t.mock.method(globalThis, "clearTimeout", function (timer) {
        assert.equal(
            this,
            globalThis,
            "clearTimeout requires the browser global",
        );
        calls.push(["clear", timer]);
    });
    const h = harness({ setTimer: undefined, clearTimer: undefined });
    await h.mic.enable();
    assert.doesNotThrow(() => h.begin());
    assert.doesNotThrow(() => h.mic.cancelInput());
    assert.deepEqual(calls, [
        ["set", CAPTURE_TIMEOUT_MS],
        ["clear", 71],
    ]);
    h.mic.disable();
    assert.ok(h.tracks.every((track) => track.stops === 1));
});

test("disable still stops every track and closes audio when timer cancellation throws", async () => {
    const h = harness({
        clearTimer: () => {
            throw new TypeError("Illegal invocation");
        },
    });
    await h.mic.enable();
    const start = h.begin();
    h.ack(start);
    await flush();
    assert.doesNotThrow(() => h.mic.disable());
    assert.equal(h.mic.enabled, false);
    assert.equal(h.mic.capture, null);
    assert.equal(h.mic.resource, null);
    assert.equal(h.mic.phase, "off");
    assert.match(h.mic.error, /Illegal invocation/);
    assert.ok(h.tracks.every((track) => track.stops === 1));
    assert.equal(h.contexts[0].closes, 1);
    assert.equal(h.detectors[0].destroys, 1);
    assert.deepEqual(h.latest("/input_cancel").body, {
        input_id: start.body.input_id,
        session_id: "session-1",
    });
});

for (const name of ["NotAllowedError", "NotFoundError"])
    test(`${name} releases resources, reports French error and makes no server call`, async () => {
        const h = harness({
            getUserMedia: async () => {
                throw Object.assign(new Error("browser"), { name });
            },
        });
        await h.mic.enable();
        assert.equal(h.mic.enabled, false);
        assert.equal(h.mic.phase, "failed");
        assert.match(h.mic.error, /continuer à écrire/);
        assert.equal(h.posts.length, 0);
        assert.equal(h.contexts[0].closes, 1);
    });

test("permission resolves after disable: every late track is stopped and no VAD starts", async () => {
    const permission = deferred();
    const h = harness({ getUserMedia: () => permission.promise });
    const opening = h.mic.enable();
    h.mic.disable();
    permission.resolve(h.stream);
    await opening;
    assert.ok(h.tracks.every((track) => track.stops === 1));
    assert.equal(h.detectors.length, 0);
    assert.equal(h.mic.enabled, false);
});

test("VAD construction completing after stop is disposed without starting", async () => {
    const loading = deferred();
    let destroys = 0,
        starts = 0;
    const h = harness({ createDetector: () => loading.promise });
    const opening = h.mic.enable();
    await flush();
    h.mic.disable();
    loading.resolve({
        async start() {
            starts++;
        },
        async destroy() {
            destroys++;
        },
    });
    await opening;
    assert.equal(starts, 0);
    assert.equal(destroys, 1);
    assert.ok(h.tracks.every((track) => track.stops === 1));
});

test("speech start mutes synchronously before HTTP and start ACK does not enable output", async () => {
    const h = harness();
    await h.mic.enable();
    const start = h.begin();
    assert.deepEqual(h.log, ["mute", "/input_start"]);
    assert.equal(h.mic.waitingForStart, true);
    h.ack(start);
    await flush();
    assert.equal(h.mic.waitingForStart, false);
    assert.equal(h.armed, false);
});

test("speech ending before start ACK waits; output is armed only after matching upload ACK", async () => {
    const h = harness();
    await h.mic.enable();
    const start = h.begin();
    h.end();
    await flush();
    assert.equal(h.latest("/input_audio"), undefined);
    h.ack(start);
    await flush();
    const upload = h.latest("/input_audio");
    assert.equal(upload.body.sample_rate, 16000);
    assert.equal(upload.body.session_id, "session-1");
    assert.equal(Buffer.from(upload.body.pcm16, "base64").length, 6400);
    assert.equal(h.armed, false);
    h.ack(upload);
    await flush();
    assert.equal(h.armed, true);
});

test("new capture defeats a late start ACK and cancels only the old input/session", async () => {
    const h = harness();
    await h.mic.enable();
    const old = h.begin(),
        current = h.begin();
    h.ack(current, "new-session");
    await flush();
    h.ack(old, "old-session");
    await flush();
    assert.deepEqual(h.latest("/input_cancel").body, {
        input_id: old.body.input_id,
        session_id: "old-session",
    });
    assert.equal(h.mic.capture.id, current.body.input_id);
    assert.equal(h.mic.capture.session, "new-session");
    assert.equal(h.log.filter((entry) => entry === "adopt").length, 1);
});

test("new capture defeats an old upload ACK without rearming stale output", async () => {
    const h = harness();
    await h.mic.enable();
    h.ack(h.begin());
    await flush();
    h.end();
    await flush();
    const oldUpload = h.latest("/input_audio");
    const current = h.begin();
    h.ack(current, "session-2");
    await flush();
    h.ack(oldUpload);
    await flush();
    assert.equal(h.armed, false);
    assert.equal(h.mic.capture.id, current.body.input_id);
});

for (const action of ["text", "stop", "pagehide"])
    test(`${action} invalidates a pending input_start and ignores its late ACK`, async () => {
        const h = harness();
        await h.mic.enable();
        const start = h.begin();
        if (action === "text") h.mic.cancelInput();
        else h.mic.disable();
        h.invalidate();
        h.ack(start);
        await flush();
        assert.equal(h.armed, false);
        assert.equal(h.mic.capture, null);
        assert.equal(
            h.latest("/input_cancel").body.input_id,
            start.body.input_id,
        );
        if (action !== "text")
            assert.ok(h.tracks.every((track) => track.stops === 1));
    });

test("misfire cancels listening and never sends audio", async () => {
    const h = harness();
    await h.mic.enable();
    h.ack(h.begin());
    await flush();
    h.detectors[0].callbacks.onMisfire();
    await flush();
    assert.equal(h.mic.capture, null);
    assert.equal(h.latest("/input_audio"), undefined);
    assert.ok(h.latest("/input_cancel"));
    assert.equal(h.armed, false);
});

test("completed transcription closes local capture without cancelling the accepted input", async () => {
    const h = harness();
    await h.mic.enable();
    const start = h.begin();
    h.ack(start);
    await flush();
    h.end();
    await flush();
    const completed = { input_id: start.body.input_id, state: "completed" };
    // State polling may beat the upload ACK. Keep the pending fence until then.
    h.mic.observe(completed);
    assert.equal(h.mic.capture.id, start.body.input_id);
    assert.equal(h.armed, false);
    h.ack(h.latest("/input_audio"));
    await flush();
    h.mic.observe(completed);
    h.mic.observe(completed);
    assert.equal(h.mic.capture, null);
    assert.equal(h.mic.phase, "ready");
    assert.equal(h.armed, true);
    h.mic.disable();
    assert.equal(h.latest("/input_cancel"), undefined);
});

test("capture deadline flushes the VAD and uploaded PCM is capped at twelve seconds", async () => {
    const h = harness();
    await h.mic.enable();
    h.ack(h.begin());
    await flush();
    const timer = [...h.timers.values()][0];
    assert.equal(timer.ms, CAPTURE_TIMEOUT_MS);
    timer.callback();
    await flush();
    assert.equal(
        Buffer.from(h.latest("/input_audio").body.pcm16, "base64").length,
        MAX_INPUT_SAMPLES * 2,
    );
    assert.equal(h.timers.size, 0);
});

test("PCM16 conversion is signed little endian, bounded, and rejects nonfinite audio", () => {
    const bytes = Buffer.from(
        pcm16Base64(new Float32Array([-2, -1, -0.5, 0, 0.5, 1, 2])),
        "base64",
    );
    assert.deepEqual(
        [...Array(7)].map((_, i) => bytes.readInt16LE(i * 2)),
        [-32768, -32768, -16384, 0, 16384, 32767, 32767],
    );
    assert.throws(() => pcm16Base64(new Float32Array()), /vide/);
    assert.throws(() => pcm16Base64(new Float32Array([NaN])), /invalide/);
});

test("disconnected microphone stops all tracks and a detector error cannot leave listening active", async () => {
    const h = harness();
    await h.mic.enable();
    h.tracks[0].ended();
    assert.equal(h.mic.enabled, false);
    assert.match(h.mic.error, /déconnecté/);
    assert.ok(h.tracks.every((track) => track.stops === 1));
});

test("failed or mismatched upload never rearms audio; ASR failure remains visible", async () => {
    const h = harness();
    await h.mic.enable();
    h.ack(h.begin());
    await flush();
    h.end();
    await flush();
    h.ack(h.latest("/input_audio"), "wrong-session");
    await flush();
    assert.equal(h.armed, false);
    assert.equal(h.mic.phase, "failed");
    const next = h.begin();
    h.ack(next);
    await flush();
    h.end();
    await flush();
    h.ack(h.latest("/input_audio"));
    await flush();
    h.mic.observe({
        input_id: next.body.input_id,
        state: "failed",
        error: "ASR indisponible",
    });
    assert.equal(h.mic.error, "ASR indisponible");
    assert.equal(h.mic.capture, null);
});

test("callbacks from a disposed detector cannot interrupt or resurrect a later activation", async () => {
    const h = harness();
    await h.mic.enable();
    const old = h.detectors[0];
    h.mic.disable();
    await h.mic.enable();
    old.callbacks.onSpeechStart();
    old.callbacks.onError(new Error("old failure"));
    assert.equal(h.posts.length, 0);
    assert.equal(h.mic.enabled, true);
    assert.equal(h.mic.phase, "ready");
});
