// Adapter tests replace MicVAD, not the capture lifecycle. No microphone/model execution.
import test from "node:test";
import assert from "node:assert/strict";
import { createSileroDetector } from "./silero-microphone.mjs";
import { CAPTURE_TIMEOUT_MS, PRE_SPEECH_PAD_MS } from "./microphone.mjs";

async function setup(overrides = {}) {
    let options,
        starts = 0,
        ends = 0,
        errors = 0,
        nativeStarts = 0,
        releases = 0,
        destroys = 0;
    const stream = {},
        context = {};
    const vad = {
        async start() {
            nativeStarts++;
        },
        async pause() {
            if (options.submitUserSpeechOnPause)
                options.onSpeechEnd(new Float32Array(16000));
        },
        async destroy() {
            destroys++;
        },
        async processFrame() {},
        setOptions(update) {
            Object.assign(options, update);
        },
        model: {
            async release() {
                releases++;
            },
        },
        ...overrides,
    };
    const detector = await createSileroDetector(
        {
            context,
            stream,
            onSpeechStart: () => starts++,
            onSpeechEnd: () => ends++,
            onMisfire: () => {},
            onError: () => errors++,
        },
        {
            assetBase: "http://127.0.0.1:2392/vad/",
            createVAD: async (value) => {
                options = value;
                return vad;
            },
        },
    );
    return {
        detector,
        vad,
        options,
        stream,
        context,
        counts: () => ({
            starts,
            ends,
            errors,
            nativeStarts,
            releases,
            destroys,
        }),
    };
}

test("Silero v5 and WASM are local and explicit; creating the detector starts no capture", async () => {
    const h = await setup();
    assert.equal(h.options.model, "v5");
    assert.equal(h.options.preSpeechPadMs, 800);
    assert.equal(h.options.preSpeechPadMs, PRE_SPEECH_PAD_MS);
    assert.equal(CAPTURE_TIMEOUT_MS, 11100);
    assert.ok(h.options.preSpeechPadMs + CAPTURE_TIMEOUT_MS < 12000);
    assert.equal(h.options.startOnLoad, false);
    assert.equal(h.options.processorType, "AudioWorklet");
    assert.equal(h.options.audioContext, h.context);
    assert.equal(h.options.baseAssetPath, "http://127.0.0.1:2392/vad/");
    assert.equal(h.options.onnxWASMBasePath, h.options.baseAssetPath);
    const ort = { env: { wasm: {} } };
    h.options.ortConfig(ort);
    assert.deepEqual(ort.env.wasm, { numThreads: 1, proxy: false });
    assert.equal(await h.options.getStream(), h.stream);
    assert.equal(await h.options.resumeStream(), h.stream);
    assert.equal(h.counts().nativeStarts, 0);
    await h.detector.destroy();
    assert.equal(h.counts().releases, 1);
    assert.equal(h.counts().destroys, 0);
});

test("maximum segment flushes once; text cancellation discards without submitting", async () => {
    const h = await setup();
    await h.detector.start();
    await h.detector.finishSegment();
    assert.equal(h.counts().ends, 1);
    await h.detector.discardSegment();
    assert.equal(h.counts().ends, 1);
    assert.equal(h.options.submitUserSpeechOnPause, true);
    await h.detector.destroy();
    await h.detector.destroy();
    assert.equal(h.counts().destroys, 1);
    h.options.onSpeechStart();
    h.options.onSpeechEnd(new Float32Array(1));
    assert.equal(h.counts().starts, 0);
    assert.equal(h.counts().ends, 1);
});

test("inference rejection is surfaced instead of an unhandled worklet promise", async () => {
    const h = await setup({
        processFrame: async () => {
            throw new Error("CPU inference unavailable");
        },
    });
    await h.vad.processFrame(new Float32Array(512));
    assert.equal(h.counts().errors, 1);
    await h.detector.destroy();
    await h.vad.processFrame(new Float32Array(512));
    assert.equal(h.counts().errors, 1);
});

test("destroy waits for pending reset and never restarts a disposed detector", async () => {
    let finishPause;
    const pause = new Promise((resolve) => {
        finishPause = resolve;
    });
    const h = await setup({ pause: () => pause });
    await h.detector.start();
    const reset = h.detector.discardSegment();
    const closing = h.detector.destroy();
    finishPause();
    await Promise.all([reset, closing]);
    assert.equal(h.counts().nativeStarts, 1);
    assert.equal(h.counts().destroys, 1);
});
