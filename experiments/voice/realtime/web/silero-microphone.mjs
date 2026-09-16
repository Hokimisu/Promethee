import { MicVAD } from "@ricky0123/vad-web";
import { PRE_SPEECH_PAD_MS } from "./microphone.mjs";

export async function createSileroDetector(
    { context, stream, onSpeechStart, onSpeechEnd, onMisfire, onError },
    { createVAD = (options) => MicVAD.new(options), assetBase } = {},
) {
    const localAssets = assetBase ?? new URL("/vad/", location.href).href;
    let disposed = false,
        started = false,
        resetting = null,
        starting = null;
    const vad = await createVAD({
        model: "v5",
        startOnLoad: false,
        processorType: "AudioWorklet",
        audioContext: context,
        baseAssetPath: localAssets,
        onnxWASMBasePath: localAssets,
        ortConfig: (ort) => {
            ort.env.wasm.numThreads = 1;
            ort.env.wasm.proxy = false;
        },
        getStream: async () => stream,
        pauseStream: async () => {},
        resumeStream: async () => stream,
        preSpeechPadMs: PRE_SPEECH_PAD_MS,
        minSpeechMs: 400,
        redemptionMs: 800,
        positiveSpeechThreshold: 0.3,
        negativeSpeechThreshold: 0.25,
        submitUserSpeechOnPause: true,
        onSpeechStart: () => {
            if (!disposed && !resetting) onSpeechStart();
        },
        onSpeechEnd: (pcm) => {
            if (!disposed) onSpeechEnd(pcm);
        },
        onVADMisfire: () => {
            if (!disposed) onMisfire();
        },
    });
    // The upstream worklet does not catch inference rejections.
    const process = vad.processFrame;
    vad.processFrame = async (frame) => {
        if (disposed) return;
        try {
            await process(frame);
        } catch (error) {
            if (!disposed) onError(error);
        }
    };
    function reset(submit) {
        if (disposed) return Promise.resolve();
        if (resetting) return resetting;
        resetting = (async () => {
            try {
                vad.setOptions({ submitUserSpeechOnPause: submit });
                await vad.pause();
                vad.setOptions({ submitUserSpeechOnPause: true });
                if (!disposed) await vad.start();
            } finally {
                resetting = null;
            }
        })();
        return resetting;
    }
    return {
        start() {
            if (disposed) return Promise.resolve();
            starting = vad.start().then(() => {
                started = true;
            });
            return starting;
        },
        finishSegment: () => reset(true),
        discardSegment: () => reset(false),
        async destroy() {
            if (disposed) return;
            disposed = true;
            await starting?.catch(() => {});
            await resetting?.catch(() => {});
            // In 0.0.31 destroy() requires initialized audio instances.
            if (started) await vad.destroy();
            else await vad.model.release();
        },
    };
}
