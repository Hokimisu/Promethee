import test from "node:test";
import assert from "node:assert/strict";
import { loadFixtureVRM } from "./vrm-fixture.mjs";
import { AudioMouth } from "./audio-mouth.mjs";

test(
    "the configured VRM has working mouth morph targets",
    { skip: !process.env.PROMETHEE_TEST_AVATAR },
    async () => {
        const vrm = await loadFixtureVRM();
        const manager = vrm.expressionManager;
        assert.ok(manager.getExpression("aa"));
        manager.setValue("aa", 0.8);
        vrm.update(0);
        const values = [];
        vrm.scene.traverse((node) => {
            if (node.morphTargetInfluences?.length > 36)
                values.push(node.morphTargetInfluences[36]);
        });
        assert.ok(values.length > 0);
        assert.ok(
            values.some((value) => value > 0.79),
            JSON.stringify(values),
        );
        let maxDelta = 0;
        vrm.scene.traverse((node) => {
            const a = node.geometry?.morphAttributes?.position?.[36];
            if (a)
                for (let i = 0; i < a.count; i++)
                    maxDelta = Math.max(
                        maxDelta,
                        Math.hypot(a.getX(i), a.getY(i), a.getZ(i)),
                    );
        });
        assert.ok(
            maxDelta > 0.001,
            "The expression must deform geometry, not only change a weight.",
        );
        console.log(
            JSON.stringify({
                aa_binds: values.length,
                max_morph_delta_m: maxDelta,
            }),
        );
        const mouth = new AudioMouth(manager);
        for (let i = 0; i < 12; i++) mouth.update(0.01844, 1 / 60);
        vrm.update(0);
        assert.ok(
            mouth.value > 0.3,
            "Quiet measured speech needs a visible opening.",
        );
        const open = mouth.value;
        mouth.reset();
        vrm.update(0);
        vrm.scene.traverse((node) => {
            if (node.morphTargetInfluences?.length > 36)
                assert.equal(node.morphTargetInfluences[36], 0);
        });
        console.log(
            JSON.stringify({
                quiet_speech_weight: open,
                max_quiet_deformation_m: open * maxDelta,
                stop_weight: mouth.value,
            }),
        );
    },
);

test("silence never opens the mouth, and decaying speech closes without an oscillator", () => {
    const values = [];
    const mouth = new AudioMouth({
        getExpression: (name) => name === "aa",
        setValue: (name, value) => values.push(value),
    });
    for (let i = 0; i < 120; i++) assert.equal(mouth.update(0, 1 / 60), 0);
    for (let i = 0; i < 12; i++) mouth.update(0.1, 1 / 60);
    assert.ok(mouth.value > 0.7);
    for (let i = 0; i < 30; i++) mouth.update(0, 1 / 60);
    assert.equal(mouth.value, 0);
    mouth.update(NaN, 1 / 60);
    assert.equal(mouth.value, 0);
});
