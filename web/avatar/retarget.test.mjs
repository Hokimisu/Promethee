import test from "node:test";
import assert from "node:assert/strict";
import { Vector3, Object3D, Quaternion } from "three";
import { rotationQuaternion, BONE_MAP, CoreRetarget } from "./retarget.js";

test("column-vector positive yaw maps forward Z to positive X", () => {
    const q = rotationQuaternion([
        [0, 0, 1],
        [0, 1, 0],
        [-1, 0, 0],
    ]);
    assert.ok(
        new Vector3(0, 0, 1)
            .applyQuaternion(q)
            .distanceTo(new Vector3(1, 0, 0)) < 1e-12,
    );
});
test("composed rotations and world hip position survive a scaled, translated hierarchy", () => {
    const scene = new Object3D();
    scene.position.set(2, 0, -1);
    const bones = {};
    let parent = scene;
    for (const name of Object.keys(BONE_MAP)) {
        const node = new Object3D();
        node.position.y = 0.02;
        parent.add(node);
        bones[name] = node;
        parent = node;
    }
    const vrm = {
        scene,
        humanoid: { getNormalizedBoneNode: (name) => bones[name] },
        update: () => {},
    };
    const skeleton = { joint_names: Object.values(BONE_MAP) };
    const target = new CoreRetarget(vrm, skeleton, 1.4);
    const yaw = [
        [0, 0, 1],
        [0, 1, 0],
        [-1, 0, 0],
    ];
    target.apply({
        positions: [[0.7, 1.1, -0.2]],
        rotations: skeleton.joint_names.map(() => yaw),
    });
    assert.ok(
        bones.hips
            .getWorldPosition(new Vector3())
            .distanceTo(new Vector3(0.7, 1.1, -0.2)) < 1e-12,
    );
    for (const node of Object.values(bones)) {
        assert.ok(
            node
                .getWorldQuaternion(new Quaternion())
                .angleTo(rotationQuaternion(yaw)) < 1e-7,
        );
    }
});
