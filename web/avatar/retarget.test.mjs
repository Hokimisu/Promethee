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
import { footSurfaceSummary } from "./foot-geometry.js";
import { capturePreparedPose, applyPreparedPose } from "./prepared-pose.js";

test("prepared poses replay independently of previous state without changing lengths", () => {
    const scene = new Object3D();
    scene.position.set(2, 0.3, -1);
    scene.rotation.y = 0.7;
    const hips = new Object3D(),
        child = new Object3D();
    scene.add(hips);
    hips.add(child);
    child.position.set(0.2, 0.4, 0.1);
    const vrm = { scene, update() {} };
    const retarget = {
        vrm,
        hips,
        bones: [
            { name: "hips", node: hips },
            { name: "child", node: child },
        ],
    };
    scene.scale.setScalar(1.3);
    hips.rotation.set(0.1, 0.2, 0.3);
    child.rotation.set(-0.4, 0.5, -0.2);
    scene.updateMatrixWorld(true);
    const record = JSON.parse(
        JSON.stringify(capturePreparedPose(retarget, -0.02)),
    );
    const length = child.position.length() * 1.3;
    const source = { positions: [[0.8, 1.2, -0.3]] };
    for (const angle of [1.5, -0.3, 0.8]) {
        hips.position.set(5, -2, 4);
        hips.rotation.set(angle, angle, angle);
        child.rotation.set(-angle, 0, angle);
        applyPreparedPose(retarget, source, record);
        assert.ok(
            hips
                .getWorldPosition(new Vector3())
                .distanceTo(new Vector3(0.8, 1.18, -0.3)) < 1e-12,
        );
        assert.ok(
            Math.abs(
                hips
                    .getWorldPosition(new Vector3())
                    .distanceTo(child.getWorldPosition(new Vector3())) - length,
            ) < 1e-12,
        );
        for (const { name, node } of retarget.bones)
            assert.ok(
                node
                    .getWorldQuaternion(new Quaternion())
                    .angleTo(new Quaternion(...record.rotations[name])) < 1e-7,
            );
    }
    const original = JSON.stringify(capturePreparedPose(retarget, -0.02));
    for (const corrupt of [
        (r) => {
            r.root_y_offset = 0.0501;
        },
        (r) => {
            r.root_y_offset = NaN;
        },
        (r) => {
            r.rotations.child = [0, 0, 0, 2];
        },
        (r) => {
            r.rotations.child = [0, 0, 0, true];
        },
        (r) => {
            delete r.rotations.child;
            r.rotations.unknown = [0, 0, 0, 1];
        },
        (r) => {
            r.positions = [[1, 2, 3]];
        },
    ]) {
        const invalid = structuredClone(record);
        corrupt(invalid);
        assert.throws(
            () => applyPreparedPose(retarget, source, invalid),
            /invalide/,
        );
        assert.equal(
            JSON.stringify(capturePreparedPose(retarget, -0.02)),
            original,
        );
    }
    assert.throws(
        () => applyPreparedPose(retarget, { positions: [[NaN, 1, 2]] }, record),
        /invalide/,
    );
    assert.equal(
        JSON.stringify(capturePreparedPose(retarget, -0.02)),
        original,
    );
});

test("VRM foot surface measurements distinguish floating feet from contact", () => {
    const summary = footSurfaceSummary([
        { left: [[0, 0.002, 0]], right: [[0, 0, 0]] },
        { left: [[0, -0.01, 0]], right: [[0, 0.02, 0]] },
        { left: [[0, 1e-8, 0]], right: [[0, 0.03, 0]] },
    ]);
    assert.equal(summary.left.frames_with_surface_contact, 1);
    assert.equal(summary.right.frames_with_surface_contact, 1);
    assert.equal(summary.left.lowest_vertex_y_m, -0.01);
    assert.equal(summary.right.highest_lowest_vertex_y_m, 0.03);
    assert.equal(summary.left.frames, 3);
    assert.throws(() => footSurfaceSummary([]), /Aucune pose/);
});

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

test("live hand blend preserves its endpoints and does not accumulate", () => {
    const scene = new Object3D(),
        bones = {};
    for (const name of Object.keys(BONE_MAP)) bones[name] = new Object3D();
    scene.add(bones.hips);
    for (const [name, node] of Object.entries(bones)) {
        if (name === "hips") continue;
        const parent =
            {
                rightUpperArm: "rightShoulder",
                rightLowerArm: "rightUpperArm",
                rightHand: "rightLowerArm",
            }[name] ?? "hips";
        bones[parent].add(node);
    }
    bones.rightUpperArm.position.set(0.15, 0.2, 0);
    bones.rightLowerArm.position.set(0.25, 0, 0);
    bones.rightHand.position.set(0.16, 0.05, 0);
    const skeleton = { joint_names: Object.values(BONE_MAP) };
    const vrm = {
        scene,
        humanoid: { getNormalizedBoneNode: (name) => bones[name] },
        update() {},
    };
    const retarget = new CoreRetarget(vrm, skeleton, 1);
    const frame = {
        positions: skeleton.joint_names.map(() => [0, 1, 0]),
        rotations: skeleton.joint_names.map(() => [
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1],
        ]),
    };
    frame.positions[skeleton.joint_names.indexOf("RightForeArm")] = [
        0.4, 1.2, 0,
    ];
    const target = new Vector3(0.45, 1.25, 0.1);
    frame.positions[skeleton.joint_names.indexOf("RightHand")] =
        target.toArray();
    retarget.apply(frame);
    const baseline = bones.rightHand.getWorldPosition(new Vector3());
    for (const weight of [0, 0.1, 0.5, 1, 0.5, 0]) {
        retarget.apply(frame, ["RightHand"], { RightHand: weight });
        assert.ok(
            bones.rightHand
                .getWorldPosition(new Vector3())
                .distanceTo(baseline.clone().lerp(target, weight)) < 1e-9,
        );
    }
    assert.throws(
        () => retarget.apply(frame, ["RightHand"], { RightHand: NaN }),
        /invalide/,
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
