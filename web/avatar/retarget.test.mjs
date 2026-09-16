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
import {
    capturePreparedPose,
    applyPreparedPose,
    expectedHandTarget,
} from "./prepared-pose.js";
import {
    settledRootLowering,
    captureFootState,
    FootPlantingTrial,
    supportPivot,
} from "./foot-planting-trial.js";

for (const [mode, lowEnd] of [
    ["toe", "heel"],
    ["heel", "toe"],
]) {
    test(`${mode} pivot uses its own sole even when the ${lowEnd} is lower`, () => {
        const root = new Object3D();
        root.position.set(2, 0, -3);
        root.rotation.y = 0.7;
        root.updateMatrixWorld(true);
        const world = (p) => root.localToWorld(new Vector3(...p));
        const heelY = mode === "heel" ? 0.03 : 0;
        const toeY = mode === "toe" ? 0.03 : 0;
        const surface = [
            [-0.02, heelY, -0.1],
            [0.02, heelY, -0.1],
            [-0.02, toeY, 0.21],
            [0.02, toeY, 0.21],
            [0, toeY + 0.01, 0.3], // Raised shoe tip is not its contact sole.
            [0, heelY + 0.01, -0.15], // Nor the raised back of the shoe.
        ].map((p) => world(p).toArray());
        const state = {
            target: world([0, 0.1, 0]),
            toe: world([0, 0.05, 0.2]),
            surface,
        };
        const before = JSON.stringify(state);
        const pivot = supportPivot(state, mode);
        assert.ok((mode === "toe" ? [2, 3] : [0, 1]).includes(pivot.vertex));
        assert.deepEqual(pivot.position.toArray(), [
            surface[pivot.vertex][0],
            0,
            surface[pivot.vertex][2],
        ]);
        assert.equal(JSON.stringify(state), before);
    });
}

test("a missing requested shoe region is rejected, not replaced by the opposite support", () => {
    const state = {
        target: new Vector3(0, 0.1, 0),
        toe: new Vector3(0, 0.05, 0.2),
        surface: [
            [0, 0, -0.1],
            [0, 0, -0.05],
        ],
    };
    assert.throws(() => supportPivot(state, "toe"), /no contact surface/);
    assert.throws(
        () => supportPivot({ ...state, toe: state.target.clone() }, "toe"),
        /direction/,
    );
});

for (const [contact, footSide] of [
    ["toe", "left"],
    ["heel", "left"],
    ["toe", "right"],
    ["heel", "right"],
]) {
    test(`${footSide} ${contact} support rolls around the shoe surface without freezing the ankle`, () => {
        const scene = new Object3D();
        scene.position.set(2, 0, -1);
        scene.rotation.y = 0.7;
        const hips = new Object3D();
        scene.add(hips);
        const nodes = { hips };
        for (const side of ["left", "right"]) {
            let parent = hips;
            for (const name of ["UpperLeg", "LowerLeg", "Foot", "Toes"]) {
                const node = new Object3D();
                parent.add(node);
                nodes[side + name] = node;
                if (name === "UpperLeg")
                    node.position.x = side === "left" ? -0.12 : 0.12;
                else if (name === "Toes") node.position.z = 0.2;
                else node.position.y = -0.4;
                parent = node;
            }
        }
        const vrm = {
            scene,
            update() {},
            humanoid: { getNormalizedBoneNode: (name) => nodes[name] },
        };
        const sole = [
            [-0.03, -0.1, -0.1],
            [0.03, -0.1, -0.1],
            [-0.03, -0.1, 0.2],
            [0.03, -0.1, 0.2],
        ];
        const geometry = {
            sample: () =>
                Object.fromEntries(
                    ["left", "right"].map((side) => [
                        side,
                        sole.map((p) =>
                            nodes[side + "Foot"]
                                .localToWorld(new Vector3(...p))
                                .toArray(),
                        ),
                    ]),
                ),
        };
        const bend = Math.acos(0.75 / 0.8);
        const retarget = {
            apply(frame) {
                scene.updateWorldMatrix(true, false);
                hips.position.copy(
                    scene.worldToLocal(new Vector3(...frame.positions[0])),
                );
                for (const side of ["left", "right"]) {
                    nodes[side + "UpperLeg"].rotation.x = bend;
                    nodes[side + "LowerLeg"].rotation.x = -2 * bend;
                    nodes[side + "Foot"].rotation.x =
                        bend + (side === footSide ? frame.pitch : 0);
                }
                scene.updateMatrixWorld(true);
            },
        };
        const rootAt = (z) =>
            new Vector3(0, 0.85, z).applyMatrix4(scene.matrixWorld).toArray();
        scene.updateMatrixWorld(true);
        retarget.apply({ positions: [rootAt(0)], pitch: 0 });
        const initial = captureFootState(vrm, geometry);
        const frozen = JSON.stringify(initial);
        const pivotIndex = contact === "toe" ? 2 : 0;
        const otherIndex = contact === "toe" ? 0 : 2;
        const pivot = new Vector3(...geometry.sample()[footSide][pivotIndex]);
        const originalAnkle = initial[footSide].target.clone();
        const solver = new FootPlantingTrial(vrm, retarget, geometry, {
            initial,
        });
        const direction = contact === "toe" ? 1 : -1;
        for (let frame = 0; frame < 20; frame++) {
            const angle =
                frame < 6
                    ? 0
                    : frame < 11
                      ? (frame - 5) * 0.1
                      : Math.max(0, (15 - frame) * 0.1);
            const pitch = direction * angle;
            const flags =
                angle === 0
                    ? [true, true]
                    : contact === "toe"
                      ? [false, true]
                      : [true, false];
            solver.apply(
                { positions: [rootAt(direction * angle * 0.2)], pitch },
                footSide === "left"
                    ? [...flags, true, true]
                    : [true, true, ...flags],
                [],
            );
            const foot = geometry.sample()[footSide];
            assert.ok(
                new Vector3(...foot[pivotIndex]).distanceTo(pivot) < 1e-6,
                `fixed contact at frame ${frame}`,
            );
            assert.ok(
                foot.every((p) => p[1] >= -1e-6),
                `sole above floor at frame ${frame}`,
            );
            if (angle >= 0.4) {
                assert.ok(
                    foot[otherIndex][1] > 0.1,
                    "opposite end rises during roll",
                );
                assert.ok(
                    nodes[footSide + "Foot"]
                        .getWorldPosition(new Vector3())
                        .distanceTo(originalAnkle) > 0.04,
                    "ankle must move while the contact stays fixed",
                );
            }
            for (const side of ["left", "right"]) {
                const positions = ["UpperLeg", "LowerLeg", "Foot"].map((name) =>
                    nodes[side + name].getWorldPosition(new Vector3()),
                );
                assert.ok(
                    Math.abs(positions[0].distanceTo(positions[1]) - 0.4) <
                        1e-8,
                );
                assert.ok(
                    Math.abs(positions[1].distanceTo(positions[2]) - 0.4) <
                        1e-8,
                );
            }
        }
        const moved = { positions: [rootAt(direction * 0.3)], pitch: 0 };
        solver.apply(
            moved,
            footSide === "left"
                ? [false, false, true, true]
                : [true, true, false, false],
            [],
        );
        solver.apply(moved, [true, true, true, true], []);
        assert.ok(
            new Vector3(...geometry.sample()[footSide][pivotIndex]).distanceTo(
                pivot,
            ) > 0.2,
            "a new stance must not reuse the contact from before the swing",
        );
        assert.equal(
            JSON.stringify(initial),
            frozen,
            "initial checkpoint remains immutable",
        );
    });
}

test("a new support solve preserves an already bent supported leg pose", () => {
    const scene = new Object3D(),
        hips = new Object3D();
    scene.add(hips);
    const nodes = { hips };
    for (const side of ["left", "right"]) {
        let parent = hips;
        for (const name of ["UpperLeg", "LowerLeg", "Foot", "Toes"]) {
            const node = new Object3D();
            parent.add(node);
            nodes[side + name] = node;
            if (name === "UpperLeg")
                node.position.x = side === "left" ? -0.1 : 0.1;
            else node.position.y = name === "Toes" ? -0.1 : -0.4;
            parent = node;
        }
    }
    const vrm = {
        scene,
        update() {},
        humanoid: { getNormalizedBoneNode: (name) => nodes[name] },
    };
    const geometry = {
        sample: () =>
            Object.fromEntries(
                ["left", "right"].map((side) => [
                    side,
                    [
                        nodes[side + "Foot"]
                            .localToWorld(new Vector3(0, -0.1, 0))
                            .toArray(),
                    ],
                ]),
            ),
    };
    hips.position.y = 0.86;
    const bend = Math.acos(0.76 / 0.8);
    for (const side of ["left", "right"]) {
        nodes[side + "UpperLeg"].rotation.x = bend;
        nodes[side + "LowerLeg"].rotation.x = -2 * bend;
        nodes[side + "Foot"].rotation.x = bend;
    }
    scene.updateMatrixWorld(true);
    const expected = Object.fromEntries(
        Object.entries(nodes).map(([name, node]) => [
            name,
            node.getWorldPosition(new Vector3()),
        ]),
    );
    const initial = captureFootState(vrm, geometry);
    const frozen = JSON.stringify(initial);
    const retarget = {
        apply(frame) {
            hips.position.set(...frame.positions[0]);
            for (const node of Object.values(nodes)) node.quaternion.identity();
            scene.updateMatrixWorld(true);
        },
    };
    for (let run = 0; run < 2; run++) {
        const solve = new FootPlantingTrial(vrm, retarget, geometry, {
            initial,
            plan: [0.04],
        });
        const offset = solve.apply(
            { positions: [[0, 0.9, 0]] },
            [true, true, true, true],
            [],
        );
        assert.ok(Math.abs(offset + 0.04) < 1e-8);
        for (const [name, node] of Object.entries(nodes))
            assert.ok(
                node
                    .getWorldPosition(new Vector3())
                    .distanceTo(expected[name]) < 1e-6,
                name,
            );
        assert.equal(JSON.stringify(initial), frozen);
    }
});

test("first support preserves the visible foot across the strict contact threshold", () => {
    for (const clearance of [0.000099, 0.000101, 0.00027872591963717036]) {
        const scene = new Object3D();
        scene.position.set(2, 0, -1);
        scene.rotation.y = 0.7;
        const hips = new Object3D();
        scene.add(hips);
        const nodes = { hips };
        for (const side of ["left", "right"]) {
            let parent = hips;
            for (const name of ["UpperLeg", "LowerLeg", "Foot", "Toes"]) {
                const node = new Object3D();
                parent.add(node);
                nodes[side + name] = node;
                if (name === "UpperLeg")
                    node.position.x = side === "left" ? -0.12 : 0.12;
                else if (name === "Toes") node.position.z = 0.2;
                else node.position.y = -0.4;
                parent = node;
            }
        }
        const vrm = {
            scene,
            update() {},
            humanoid: { getNormalizedBoneNode: (name) => nodes[name] },
        };
        const geometry = {
            sample: () =>
                Object.fromEntries(
                    ["left", "right"].map((side) => [
                        side,
                        [-0.1, 0.2].map((z) =>
                            nodes[side + "Foot"]
                                .localToWorld(new Vector3(0, -0.1, z))
                                .toArray(),
                        ),
                    ]),
                ),
        };
        const bend = Math.acos(0.75 / 0.8);
        const retarget = {
            apply(frame) {
                hips.position.copy(
                    scene.worldToLocal(new Vector3(...frame.positions[0])),
                );
                for (const side of ["left", "right"]) {
                    nodes[side + "UpperLeg"].rotation.x = bend;
                    nodes[side + "LowerLeg"].rotation.x = -2 * bend;
                    nodes[side + "Foot"].rotation.set(bend, frame.yaw, 0);
                    nodes[side + "Toes"].rotation.y = frame.yaw;
                }
                scene.updateMatrixWorld(true);
            },
        };
        scene.updateMatrixWorld(true);
        const rootAt = (x, z) =>
            new Vector3(x, 0.85 + clearance, z)
                .applyMatrix4(scene.matrixWorld)
                .toArray();
        retarget.apply({ positions: [rootAt(0, 0)], yaw: 0 });
        const initial = captureFootState(vrm, geometry);
        const frozen = JSON.stringify(initial);
        for (const side of ["left", "right"])
            assert.equal(initial[side].supporting, clearance <= 0.0001);
        const solver = new FootPlantingTrial(vrm, retarget, geometry, {
            initial,
        });
        let previousOffset = null;
        for (let frame = 0; frame < 8; frame++) {
            const offset = solver.apply(
                { positions: [rootAt(0.008, 0.012)], yaw: 0.03 },
                [true, true, true, true],
                [],
            );
            const current = captureFootState(vrm, geometry);
            for (const side of ["left", "right"]) {
                assert.ok(current[side].supporting, "measured surface contact");
                for (const axis of ["x", "z"])
                    assert.ok(
                        Math.abs(
                            current[side].target[axis] -
                                initial[side].target[axis],
                        ) < 1e-8,
                        `${side} ${axis} must not slide at frame ${frame}`,
                    );
                for (const name of ["rotation", "toeRotation"])
                    assert.ok(
                        current[side][name].angleTo(initial[side][name]) < 1e-7,
                        `${side} ${name} must preserve the visible pose`,
                    );
                for (const [index, point] of current[side].surface.entries()) {
                    assert.ok(Math.abs(point[1]) <= 0.0001);
                    const before = initial[side].surface[index];
                    assert.ok(
                        Math.hypot(point[0] - before[0], point[2] - before[2]) <
                            1e-8,
                        "the same sole vertices remain fixed in XZ",
                    );
                }
            }
            if (previousOffset !== null)
                assert.ok(Math.abs(offset - previousOffset) <= 0.015);
            previousOffset = offset;
        }
        assert.equal(JSON.stringify(initial), frozen);
    }
});

test("skin settling satisfies both root and contact budgets at their boundary", () => {
    assert.equal(settledRootLowering(0.02, 0.001), 0.021);
    for (const sign of [-1, 1]) {
        const lowering = sign * 0.04984;
        const residual = sign * 0.000253;
        const result = settledRootLowering(lowering, residual);
        assert.equal(Math.abs(result), 0.05);
        assert.ok(Math.abs(lowering + residual - result) <= 0.0001);
        assert.throws(() => settledRootLowering(sign * 0.0499, sign * 0.0003));
    }
    for (const value of [NaN, Infinity, -Infinity]) {
        assert.throws(() => settledRootLowering(value, 0));
        assert.throws(() => settledRootLowering(0, value));
    }
});

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

test("live hand blend preserves endpoints and observed partial alignment without accumulating", () => {
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
        humanoid: {
            getNormalizedBoneNode: (name) => bones[name],
            getRawBoneNode: (name) => bones[name],
        },
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
    for (const weight of [0, 0.1, 0.4, 0.5, 1, 0.5, 0]) {
        const expected = baseline.clone().lerp(target, weight);
        retarget.apply(frame);
        assert.ok(
            expectedHandTarget(retarget, frame, "RightHand", weight).distanceTo(
                expected,
            ) < 1e-9,
        );
        retarget.apply(frame, ["RightHand"], { RightHand: weight });
        assert.ok(
            bones.rightHand
                .getWorldPosition(new Vector3())
                .distanceTo(expected) < 1e-9,
        );
        const prepared = capturePreparedPose(retarget, 0);
        retarget.apply(frame);
        applyPreparedPose(retarget, frame, prepared);
        assert.ok(
            expectedHandTarget(retarget, frame, "RightHand", weight, {
                observedOrigin: true,
            }).distanceTo(expected) < 1e-9,
            `the restored ${weight} alignment must not blend a second time`,
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
