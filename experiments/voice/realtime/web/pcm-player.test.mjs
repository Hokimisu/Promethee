import test from "node:test";
import assert from "node:assert/strict";
import { PCMPlayer } from "./pcm-player.js";

test("rendered amplitude ignores queued, stale, suspended and muted playback", () => {
    const p = new PCMPlayer();
    p.context = { state: "running", currentTime: 0 };
    p.gain = {
        gain: {
            value: 1,
            cancelScheduledValues() {},
            setValueAtTime(value) {
                this.value = value;
            },
        },
    };
    p.stats = {
        played_frames: 128,
        buffered_frames: 48000,
        underflows: 0,
        rms: 0.2,
    };
    p.statsAt = performance.now();
    assert.equal(p.renderedRms, 0, "Queued PCM is not playing yet.");
    p.playing = "a";
    assert.equal(p.renderedRms, 0.2);
    p.statsAt = performance.now() - 200;
    assert.equal(p.renderedRms, 0);
    p.statsAt = performance.now();
    p.context.state = "suspended";
    assert.equal(p.renderedRms, 0);
    p.context.state = "running";
    p.reset();
    assert.equal(p.renderedRms, 0);
    assert.equal(p.gain.gain.value, 0);
    assert.equal(p.stats.rms, 0);
});
