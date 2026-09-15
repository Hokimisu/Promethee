import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { Vector3, Object3D, Quaternion } from "three";
import {
    rotationQuaternion,
    BONE_MAP,
    CoreRetarget,
    validateArmProfile,
} from "./retarget.js";
import { ObjectVisuals } from "./objects.js";
import { alignHand } from "./align-hand.js";

test("appearance profile refuses changed scale, geometry and parentage", () => {
    const profile = JSON.parse(
        readFileSync(
            new URL(
                "../../src/promethee/pixiv_arm_profile.json",
                import.meta.url,
            ),
        ),
    );
    const root = new Object3D(),
        nodes = {};
    for (const [name, bone] of Object.entries(profile.bones)) {
        const node = new Object3D();
        (nodes[bone.parent] ?? root).add(node);
        node.position.fromArray(bone.rest_position);
        if (bone.parent)
            node.position.sub(
                new Vector3(...profile.bones[bone.parent].rest_position),
            );
        nodes[name] = node;
    }
    root.updateMatrixWorld(true);
    const vrm = { humanoid: { getNormalizedBoneNode: (name) => nodes[name] } };
    const skeleton = { neutral_joints: [[0, -profile.core_hip_height, 0]] };
    validateArmProfile(vrm, skeleton, profile.scale, profile);
    assert.throws(
        () => validateArmProfile(vrm, skeleton, profile.scale + 0.01, profile),
        /échelle/,
    );
    nodes.rightHand.position.x += 0.001;
    root.updateMatrixWorld(true);
    assert.throws(
        () => validateArmProfile(vrm, skeleton, profile.scale, profile),
        /géométrie/,
    );
    nodes.rightHand.position.x -= 0.001;
    root.attach(nodes.rightHand);
    assert.throws(
        () => validateArmProfile(vrm, skeleton, profile.scale, profile),
        /géométrie/,
    );
});

test("hand alignment reaches a world target without stretching the arm", () => {
    const root = new Object3D(),
        upper = new Object3D(),
        lower = new Object3D(),
        hand = new Object3D();
    root.position.set(1, 1, -1);
    root.scale.setScalar(1.2);
    root.add(upper);
    upper.add(lower);
    lower.add(hand);
    lower.position.set(0.25, 0, 0);
    hand.position.set(0.2, 0, 0);
    root.updateMatrixWorld(true);
    const target = new Vector3(1.25, 1.2, -0.8);
    alignHand(upper, lower, hand, target, new Vector3(1.1, 1.3, -1));
    assert.ok(hand.getWorldPosition(new Vector3()).distanceTo(target) < 1e-10);
    assert.ok(
        Math.abs(
            upper
                .getWorldPosition(new Vector3())
                .distanceTo(lower.getWorldPosition(new Vector3())) - 0.3,
        ) < 1e-10,
    );
    assert.ok(
        Math.abs(
            lower
                .getWorldPosition(new Vector3())
                .distanceTo(hand.getWorldPosition(new Vector3())) - 0.24,
        ) < 1e-10,
    );
    assert.ok(
        hand.getWorldQuaternion(new Quaternion()).angleTo(new Quaternion()) <
            1e-7,
    );
    assert.throws(
        () => alignHand(upper, lower, hand, new Vector3(4, 1, -1), target),
        /hors de portée/,
    );
});

test("object render follows the recorded world pose and removes absent objects", () => {
    const scene = new Object3D();
    const visual = new ObjectVisuals(scene, {
        plush: [{ center: [0, 0, 0], size: [0.1, 0.2, 0.1], color: "#c99c73" }],
    });
    const item = {
        asset: "plush",
        spatial: {
            position: [1, 0.8, -0.4],
            rotation: [
                [0, 0, 1],
                [0, 1, 0],
                [-1, 0, 0],
            ],
        },
    };
    visual.display({ item });
    const node = visual.nodes.get("item").node;
    assert.deepEqual(
        node.getWorldPosition(new Vector3()).toArray(),
        item.spatial.position,
    );
    assert.ok(
        node.quaternion.angleTo(rotationQuaternion(item.spatial.rotation)) <
            1e-7,
    );
    item.spatial.position = [1.1, 0.9, -0.3];
    visual.display({ item });
    assert.equal(visual.nodes.get("item").node, node);
    assert.deepEqual(node.position.toArray(), item.spatial.position);
    visual.display({});
    assert.equal(scene.children.length, 0);
    assert.equal(visual.nodes.size, 0);
});

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
