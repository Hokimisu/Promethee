// Experimental replay correction. Not imported by the live renderer.
import { Quaternion, Vector3 } from "three";
import { alignHand } from "./align-hand.js";

function worldRotation(node, value) {
    node.parent.updateWorldMatrix(true, false);
    node.quaternion.copy(
        node.parent
            .getWorldQuaternion(new Quaternion())
            .invert()
            .multiply(value),
    );
    node.updateMatrixWorld(true);
}

export function settledRootLowering(lowering, skinHeight) {
    const requested = lowering + skinHeight;
    const bounded = Math.max(-0.05, Math.min(0.05, requested));
    if (!Number.isFinite(requested) || Math.abs(requested - bounded) > 0.0001)
        throw new Error(
            `Combined VRM root correction exceeds 5 cm outside the 0.1 mm surface contact tolerance: ${requested} m.`,
        );
    return bounded;
}

export class FootPlantingTrial {
    constructor(
        vrm,
        retarget,
        geometry,
        { plan = null, collect = false } = {},
    ) {
        this.vrm = vrm;
        this.retarget = retarget;
        this.geometry = geometry;
        this.anchors = {};
        this.previousOffset = null;
        this.plan = plan;
        this.collect = collect;
        this.required = [];
    }

    apply(frame, contacts, hands) {
        if (
            !Array.isArray(contacts) ||
            contacts.length !== 4 ||
            !contacts.every((x) => typeof x === "boolean")
        )
            throw new Error("Expected the four archived ARDY contact flags.");
        if (!contacts.some(Boolean))
            throw new Error("No predicted foot support.");
        this.retarget.apply(frame, hands);
        const baseline = this.geometry.sample();
        const sides = ["left", "right"];
        const targets = {};
        const rotations = {};
        const toeRotations = {};
        const guides = {};
        const bone = (side, name) =>
            this.vrm.humanoid.getNormalizedBoneNode(side + name);
        let lowering = 0;
        for (const [index, side] of sides.entries()) {
            const nodes = ["UpperLeg", "LowerLeg", "Foot"].map((name) =>
                bone(side, name),
            );
            const [hip, knee, ankle] = nodes.map((node) =>
                node.getWorldPosition(new Vector3()),
            );
            guides[side] = knee;
            const height = Math.min(...baseline[side].map((p) => p[1]));
            const supporting = contacts[index * 2] || contacts[index * 2 + 1];
            if (!supporting) delete this.anchors[side];
            if (supporting && !this.anchors[side]) {
                this.anchors[side] = {
                    target: ankle.clone().add(new Vector3(0, -height, 0)),
                    rotation: nodes[2].getWorldQuaternion(new Quaternion()),
                    toeRotation: bone(side, "Toes").getWorldQuaternion(
                        new Quaternion(),
                    ),
                };
            }
            targets[side] =
                this.anchors[side]?.target.clone() ??
                ankle
                    .clone()
                    .add(new Vector3(0, Math.max(0, 0.01 - height), 0));
            rotations[side] =
                this.anchors[side]?.rotation ??
                nodes[2].getWorldQuaternion(new Quaternion());
            toeRotations[side] =
                this.anchors[side]?.toeRotation ??
                bone(side, "Toes").getWorldQuaternion(new Quaternion());
            const length = hip.distanceTo(knee) + knee.distanceTo(ankle) - 1e-5;
            const horizontal = Math.hypot(
                hip.x - targets[side].x,
                hip.z - targets[side].z,
            );
            if (horizontal >= length)
                throw new Error("VRM support exceeds horizontal leg reach.");
            lowering = Math.max(
                lowering,
                hip.y -
                    targets[side].y -
                    Math.sqrt(length ** 2 - horizontal ** 2),
            );
        }
        this.required.push(lowering);
        if (this.plan) {
            const planned = this.plan[this.required.length - 1];
            if (!Number.isFinite(planned) || planned < lowering - 1e-8)
                throw new Error(
                    "Planned VRM lowering does not cover leg reach.",
                );
            lowering = planned;
        }
        if (lowering > 0.05)
            throw new Error(
                "VRM support requires more than 5 cm pelvis lowering.",
            );
        if (
            !this.collect &&
            this.previousOffset !== null &&
            Math.abs(lowering - this.previousOffset) > 0.015 + 1e-8
        )
            throw new Error(
                "VRM support exceeds 15 mm/frame pelvis correction.",
            );
        this.previousOffset = lowering;
        const positions = frame.positions.map((p) => [...p]);
        positions[0][1] -= lowering;
        this.retarget.apply({ ...frame, positions }, hands);
        for (const side of sides) {
            worldRotation(bone(side, "Foot"), rotations[side]);
            alignHand(
                bone(side, "UpperLeg"),
                bone(side, "LowerLeg"),
                bone(side, "Foot"),
                targets[side],
                guides[side],
            );
            worldRotation(bone(side, "Toes"), toeRotations[side]);
        }
        this.vrm.update(0);
        this.vrm.scene.updateMatrixWorld(true);
        const finalFeet = this.geometry.sample();
        const height = Math.min(
            ...Object.values(finalFeet).flatMap((foot) =>
                foot.map((p) => p[1]),
            ),
        );
        if (!Number.isFinite(height))
            throw new Error("Non-finite VRM skin-floor residual.");
        // Keep the existing root budget and surface tolerance simultaneously.
        // The final mesh measurement still decides whether a foot is in contact.
        const settled = settledRootLowering(lowering, height);
        const hips = this.vrm.humanoid.getNormalizedBoneNode("hips");
        const target = hips.getWorldPosition(new Vector3());
        target.y -= settled - lowering;
        hips.position.copy(hips.parent.worldToLocal(target));
        hips.updateMatrixWorld(true);
        for (const hand of hands) {
            const side = hand === "RightHand" ? "right" : "left";
            const elbow = hand === "RightHand" ? "RightForeArm" : "LeftForeArm";
            alignHand(
                bone(side, "UpperArm"),
                bone(side, "LowerArm"),
                bone(side, "Hand"),
                new Vector3(
                    ...frame.positions[
                        this.retarget.skeleton.joint_names.indexOf(hand)
                    ],
                ),
                new Vector3(
                    ...frame.positions[
                        this.retarget.skeleton.joint_names.indexOf(elbow)
                    ],
                ),
            );
        }
        this.vrm.update(0);
        this.vrm.scene.updateMatrixWorld(true);
        return -settled;
    }
}
