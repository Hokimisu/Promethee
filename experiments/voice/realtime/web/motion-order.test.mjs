// Execute the actual browser receive/draw functions on a CPU Three skeleton.
// No VRM fixture, rendering context, model, browser or GPU is required.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as THREE from "../../../../web/avatar/node_modules/three/build/three.module.js";

const app = readFileSync(new URL("./app.js", import.meta.url), "utf8");
const functions = app.slice(
    app.indexOf("function receiveMotion("),
    app.indexOf("async function pollState("),
);
const names = [
    "hips",
    "spine",
    "neck",
    "head",
    "leftUpperLeg",
    "leftLowerLeg",
    "leftFoot",
    "rightUpperLeg",
    "rightLowerLeg",
    "rightFoot",
];
const parents = [
    null,
    "hips",
    "spine",
    "neck",
    "hips",
    "leftUpperLeg",
    "leftLowerLeg",
    "hips",
    "rightUpperLeg",
    "rightLowerLeg",
];
const rotationByName = Object.fromEntries(
    names.map((name, index) => [
        name,
        new THREE.Quaternion()
            .setFromEuler(
                new THREE.Euler(index * 0.08, index * -0.05, index * 0.03),
            )
            .toArray(),
    ]),
);

function reader() {
    const scene = new THREE.Group(),
        nodes = new Map();
    names.forEach((name, index) => {
        const node = new THREE.Object3D();
        node.name = name;
        node.position.set(
            index % 2 ? 0.13 : -0.11,
            name.includes("Leg") ? -0.3 : 0.16,
            0.03,
        );
        (parents[index] ? nodes.get(parents[index]) : scene).add(node);
        nodes.set(name, node);
    });
    const vrm = {
        scene,
        humanoid: { getNormalizedBoneNode: (name) => nodes.get(name) },
    };
    // This compiles existing app functions, rather than copying their mapping logic.
    return new Function(
        "THREE",
        "vrm",
        `
        let freezeMotion=false,motionId=null,motionSequence=-1,motionFrames=[],boneNodes=[],visiblePose=false;
        let clock=0;
        const performance={now:()=>clock},Date={now:()=>10000+clock};
        const hips=vrm.humanoid.getNormalizedBoneNode('hips');
        const q1=new THREE.Quaternion(),q2=new THREE.Quaternion(),parentQ=new THREE.Quaternion(),root=new THREE.Vector3(),root2=new THREE.Vector3();
        ${functions}
        return {
            receive(motion,at){clock=at;receiveMotion(motion);},
            draw(at){drawPose(at);vrm.scene.updateMatrixWorld(true);},
            get frames(){return motionFrames;},get bindings(){return boneNodes;},
            node(name){return vrm.humanoid.getNormalizedBoneNode(name);}
        };
    `,
    )(THREE, vrm);
}
function motion(order, sequence, at) {
    return {
        id: "same-controller",
        sequence,
        scale: 1,
        rotation_space: "normalized-bone-world",
        root_space: "world",
        bone_names: order,
        sampled_at_unix_ms: 10000 + at,
        frames: [
            {
                root_position: [0.2, 1, -0.1],
                rotations: order.map((name) => rotationByName[name]),
            },
        ],
    };
}
function assertPoseByName(actual, expected) {
    for (const name of names) {
        const a = actual.node(name),
            b = expected.node(name);
        assert.ok(
            a
                .getWorldPosition(new THREE.Vector3())
                .distanceTo(b.getWorldPosition(new THREE.Vector3())) < 1e-12,
            `${name} position`,
        );
        const qa = a.getWorldQuaternion(new THREE.Quaternion()),
            qb = b.getWorldQuaternion(new THREE.Quaternion());
        assert.ok(1 - Math.abs(qa.dot(qb)) < 1e-12, `${name} world rotation`);
    }
}

test("same controller can resume from alphabetical checkpoint into hierarchical bone order", () => {
    const live = reader(),
        fresh = reader();
    live.receive(motion([...names].sort(), 501, 0), 0);
    live.draw(100);
    const resumed = motion(names, 4333, 50);
    live.receive(resumed, 50);
    live.draw(150);
    fresh.receive(resumed, 50);
    fresh.draw(150);
    assert.equal(live.frames.length, 1);
    for (const binding of live.bindings)
        assert.equal(resumed.bone_names[binding.index], binding.node.name);
    assertPoseByName(live, fresh);
});

test("layout change discards older buffered arrays even when the sequence is unchanged", () => {
    const live = reader(),
        fresh = reader(),
        alphabetical = [...names].sort();
    live.receive(motion(alphabetical, 1, 0), 0);
    live.receive(motion(alphabetical, 2, 50), 50);
    assert.equal(live.frames.length, 2);
    const previousBindings = live.bindings;
    const changed = motion(names, 2, 100);
    live.receive(changed, 100);
    assert.equal(live.frames.length, 1);
    assert.equal(live.frames[0].frame, changed.frames[0]);
    assert.notEqual(live.bindings, previousBindings);
    // Playback target is still between old timestamps. Only the new layout may be drawn.
    live.draw(125);
    fresh.receive(changed, 100);
    fresh.draw(125);
    assertPoseByName(live, fresh);
});

test("unchanged layout retains interpolation history; reordered stale sequence is ignored", () => {
    const live = reader();
    live.receive(motion(names, 10, 0), 0);
    const bindings = live.bindings;
    live.receive(motion(names, 11, 50), 50);
    assert.equal(live.bindings, bindings);
    assert.equal(live.frames.length, 2);
    live.receive(motion([...names].sort(), 9, 100), 100);
    assert.equal(live.bindings, bindings);
    assert.equal(live.frames.length, 2);
});
