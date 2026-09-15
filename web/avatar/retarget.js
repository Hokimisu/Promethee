import { Matrix4, Quaternion, Vector3 } from "three";
import { alignHand } from "./align-hand.js";

// Core's intermediate Spine1 is represented by the composed world rotation of chest.
// These are named joints from the pinned Core27 export, not VRM raw bone indices.
export const BONE_MAP = {
    hips: "Hips",
    spine: "Spine",
    chest: "Spine2",
    upperChest: "Spine3",
    neck: "Neck",
    head: "Head",
    rightShoulder: "RightShoulder",
    rightUpperArm: "RightArm",
    rightLowerArm: "RightForeArm",
    rightHand: "RightHand",
    leftShoulder: "LeftShoulder",
    leftUpperArm: "LeftArm",
    leftLowerArm: "LeftForeArm",
    leftHand: "LeftHand",
    rightUpperLeg: "RightUpLeg",
    rightLowerLeg: "RightLeg",
    rightFoot: "RightFoot",
    rightToes: "RightToeBase",
    leftUpperLeg: "LeftUpLeg",
    leftLowerLeg: "LeftLeg",
    leftFoot: "LeftFoot",
    leftToes: "LeftToeBase",
};

export function validateArmProfile(vrm, skeleton, scale, profile) {
    if (
        !profile ||
        profile.version !== 1 ||
        Math.abs(scale - profile.scale) > 1e-8 ||
        Math.abs(
            -Math.min(...skeleton.neutral_joints.map((p) => p[1])) -
                profile.core_hip_height,
        ) > 1e-6
    )
        throw new Error(
            "L’échelle de l’avatar diffère du profil de portée du contrôleur.",
        );
    for (const [name, bone] of Object.entries(profile.bones)) {
        const node = vrm.humanoid.getNormalizedBoneNode(name);
        const parent =
            bone.parent && vrm.humanoid.getNormalizedBoneNode(bone.parent);
        if (
            !node ||
            BONE_MAP[name] !== bone.source ||
            (parent && node.parent !== parent) ||
            node
                .getWorldPosition(new Vector3())
                .distanceTo(new Vector3(...bone.rest_position)) > 1e-6
        )
            throw new Error(
                `La géométrie de l’avatar diffère du profil de portée : ${name}.`,
            );
    }
}

export function rotationQuaternion(rows) {
    const m = new Matrix4().set(
        ...rows[0],
        0,
        ...rows[1],
        0,
        ...rows[2],
        0,
        0,
        0,
        0,
        1,
    );
    return new Quaternion().setFromRotationMatrix(m).normalize();
}

export class CoreRetarget {
    constructor(vrm, skeleton, scale) {
        this.vrm = vrm;
        this.skeleton = skeleton;
        vrm.scene.scale.setScalar(scale);
        vrm.scene.updateMatrixWorld(true);
        this.bones = Object.entries(BONE_MAP).map(([name, source]) => {
            const node = vrm.humanoid.getNormalizedBoneNode(name);
            const index = skeleton.joint_names.indexOf(source);
            if (!node || index < 0)
                throw new Error(`Articulation manquante : ${name} / ${source}`);
            return {
                name,
                node,
                index,
                restWorld: node.getWorldQuaternion(new Quaternion()),
            };
        });
        // Ensure parent world rotations are resolved before their children, even for a different VRM hierarchy.
        const depth = (node) => {
            let n = 0;
            while (node.parent) {
                n++;
                node = node.parent;
            }
            return n;
        };
        this.bones.sort((a, b) => depth(a.node) - depth(b.node));
        this.hips = vrm.humanoid.getNormalizedBoneNode("hips");
    }

    apply(frame, attachedHands = [], handWeights = {}) {
        for (const { node, index, restWorld } of this.bones) {
            node.parent.updateWorldMatrix(true, false);
            const desired = rotationQuaternion(frame.rotations[index]).multiply(
                restWorld,
            );
            node.quaternion.copy(
                node.parent
                    .getWorldQuaternion(new Quaternion())
                    .invert()
                    .multiply(desired),
            );
            node.updateMatrixWorld(true);
        }
        const position = new Vector3(...frame.positions[0]);
        this.hips.parent.updateWorldMatrix(true, false);
        this.hips.position.copy(this.hips.parent.worldToLocal(position));
        this.hips.updateMatrixWorld(true);
        this.alignHands(frame, attachedHands, handWeights);
    }

    alignHands(frame, attachedHands = [], handWeights = {}) {
        for (const name of new Set(attachedHands)) {
            const weight = handWeights[name] ?? 1;
            if (!Number.isFinite(weight) || weight < 0 || weight > 1)
                throw new Error("Adaptation de main invalide.");
            if (weight === 0) continue;
            const side =
                name === "RightHand"
                    ? "right"
                    : name === "LeftHand"
                      ? "left"
                      : null;
            if (!side) throw new Error("Articulation d’attachement inconnue.");
            const index = this.skeleton.joint_names.indexOf(name);
            const elbow = this.skeleton.joint_names.indexOf(
                name === "RightHand" ? "RightForeArm" : "LeftForeArm",
            );
            const hand = this.vrm.humanoid.getNormalizedBoneNode(`${side}Hand`);
            const target = hand
                .getWorldPosition(new Vector3())
                .lerp(new Vector3(...frame.positions[index]), weight);
            alignHand(
                this.vrm.humanoid.getNormalizedBoneNode(`${side}UpperArm`),
                this.vrm.humanoid.getNormalizedBoneNode(`${side}LowerArm`),
                hand,
                target,
                new Vector3(...frame.positions[elbow]),
            );
        }
        this.vrm.update(0); // No procedural idle, spring animation or invented inter-frame motion.
        this.vrm.scene.updateMatrixWorld(true);
    }
}
