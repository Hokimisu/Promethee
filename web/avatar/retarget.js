import { Matrix4, Quaternion, Vector3 } from "three";

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
        vrm.scene.scale.setScalar(scale);
        vrm.scene.updateMatrixWorld(true);
        this.bones = Object.entries(BONE_MAP).map(([name, source]) => {
            const node = vrm.humanoid.getNormalizedBoneNode(name);
            const index = skeleton.joint_names.indexOf(source);
            if (!node || index < 0)
                throw new Error(`Articulation manquante : ${name} / ${source}`);
            return {
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

    apply(frame) {
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
        this.vrm.update(0); // No procedural idle, spring animation or invented inter-frame motion.
        this.vrm.scene.updateMatrixWorld(true);
    }
}
