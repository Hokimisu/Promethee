import { Quaternion, Vector3 } from "three";

function setWorldRotation(node, rotation) {
    node.parent.updateWorldMatrix(true, false);
    node.quaternion.copy(
        node.parent
            .getWorldQuaternion(new Quaternion())
            .invert()
            .multiply(rotation),
    );
    node.updateMatrixWorld(true);
}

export function alignHand(upper, lower, hand, target, guide) {
    const a = upper.getWorldPosition(new Vector3());
    const b = lower.getWorldPosition(new Vector3());
    const c = hand.getWorldPosition(new Vector3());
    const length1 = a.distanceTo(b),
        length2 = b.distanceTo(c);
    const direction = target.clone().sub(a),
        distance = direction.length();
    if (
        distance <= Math.abs(length1 - length2) + 1e-6 ||
        distance >= length1 + length2 - 1e-6
    )
        throw new Error(
            `Cible de main hors de portée du bras de cet avatar (${distance.toFixed(3)} m ; maximum ${(length1 + length2).toFixed(3)} m).`,
        );
    direction.normalize();
    let bend = guide.clone().sub(a);
    bend.addScaledVector(direction, -bend.dot(direction));
    if (bend.length() < 1e-6) {
        bend = b.clone().sub(a);
        bend.addScaledVector(direction, -bend.dot(direction));
    }
    if (bend.length() < 1e-6)
        throw new Error("Plan de flexion du coude indéterminé.");
    const along =
        (length1 ** 2 - length2 ** 2 + distance ** 2) / (2 * distance);
    const elbow = a
        .clone()
        .addScaledVector(direction, along)
        .addScaledVector(
            bend.normalize(),
            Math.sqrt(Math.max(0, length1 ** 2 - along ** 2)),
        );
    const handRotation = hand.getWorldQuaternion(new Quaternion());
    const upperRotation = upper.getWorldQuaternion(new Quaternion());
    setWorldRotation(
        upper,
        new Quaternion()
            .setFromUnitVectors(
                b.clone().sub(a).normalize(),
                elbow.clone().sub(a).normalize(),
            )
            .multiply(upperRotation),
    );
    const actualElbow = lower.getWorldPosition(new Vector3());
    const actualHand = hand.getWorldPosition(new Vector3());
    setWorldRotation(
        lower,
        new Quaternion()
            .setFromUnitVectors(
                actualHand.sub(actualElbow).normalize(),
                target.clone().sub(actualElbow).normalize(),
            )
            .multiply(lower.getWorldQuaternion(new Quaternion())),
    );
    setWorldRotation(hand, handRotation);
    if (hand.getWorldPosition(new Vector3()).distanceTo(target) > 1e-5)
        throw new Error("La main affichée n’atteint pas sa position observée.");
}
