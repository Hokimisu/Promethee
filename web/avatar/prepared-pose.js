import { Quaternion, Vector3 } from "three";

export function capturePreparedPose(retarget, rootOffset) {
    return {
        root_y_offset: rootOffset,
        rotations: Object.fromEntries(
            retarget.bones.map(({ name, node }) => [
                name,
                node.getWorldQuaternion(new Quaternion()).toArray(),
            ]),
        ),
    };
}

export function applyPreparedPose(retarget, source, prepared) {
    const names = retarget.bones.map(({ name }) => name);
    if (
        !Array.isArray(source?.positions?.[0]) ||
        source.positions[0].length !== 3 ||
        !source.positions[0].every(Number.isFinite) ||
        !prepared ||
        Object.keys(prepared).sort().join() !== "root_y_offset,rotations" ||
        !Number.isFinite(prepared.root_y_offset) ||
        Math.abs(prepared.root_y_offset) > 0.05 ||
        !prepared.rotations ||
        Array.isArray(prepared.rotations) ||
        Object.keys(prepared.rotations).length !== names.length
    )
        throw new Error("Pose d’apparence préparée invalide.");
    // Validate the entire record before mutating the visible skeleton.
    for (const name of names) {
        const q = prepared.rotations[name];
        if (
            !Array.isArray(q) ||
            q.length !== 4 ||
            !q.every(Number.isFinite) ||
            Math.abs(Math.hypot(...q) - 1) > 1e-6
        )
            throw new Error("Rotation d’apparence préparée invalide.");
    }
    for (const { name, node } of retarget.bones) {
        node.parent.updateWorldMatrix(true, false);
        node.quaternion.copy(
            node.parent
                .getWorldQuaternion(new Quaternion())
                .invert()
                .multiply(new Quaternion(...prepared.rotations[name])),
        );
        node.updateMatrixWorld(true);
    }
    const root = new Vector3(...source.positions[0]);
    root.y += prepared.root_y_offset;
    retarget.hips.parent.updateWorldMatrix(true, false);
    retarget.hips.position.copy(retarget.hips.parent.worldToLocal(root));
    retarget.hips.updateMatrixWorld(true);
    retarget.vrm.update(0);
    retarget.vrm.scene.updateMatrixWorld(true);
}
