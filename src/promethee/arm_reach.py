"""Geometric Core arm reaching, not yet a grasp or a collision-qualified action."""

from promethee.ardy_contacts import between
from promethee.pose import validate_pose

ARMS = {
    "right": ("RightArm", "RightForeArm", "RightHand", "RightHandEnd"),
    "left": ("LeftArm", "LeftForeArm", "LeftHand", "LeftHandEnd"),
}


def forward_positions(rotations, root, skeleton):
    """Reconstruct Core positions from global rotations and rest bone offsets."""
    import numpy as np

    neutral = np.asarray(skeleton["neutral_joints"], dtype=float)
    parents = skeleton["parents"]
    if (
        neutral.shape != (27, 3)
        or not np.isfinite(neutral).all()
        or len(parents) != 27
        or parents[0] != -1
    ):
        raise ValueError("Expected the qualified 27-joint Core hierarchy.")
    points = np.empty((27, 3))
    points[0] = root
    for joint in range(1, 27):
        parent = parents[joint]
        if type(parent) is not int or not 0 <= parent < joint:
            raise ValueError("Core joints must be ordered after their parents.")
        points[joint] = points[parent] + rotations[parent] @ (neutral[joint] - neutral[parent])
    return points


def interpolate_rotation(start, end, phase):
    """Shortest SO(3) arc; choose a deterministic axis for an exact half turn."""
    import numpy as np

    # Stored float32 poses accumulate small orthogonality errors. Project only
    # the interpolation endpoints onto SO(3), so acos/skew do not amplify them
    # near a half turn. Input pose validation rejects malformed rotations first.
    def proper(matrix):
        u, _, vt = np.linalg.svd(matrix)
        return u @ np.diag([1, 1, np.linalg.det(u @ vt)]) @ vt

    start, end = proper(start), proper(end)
    delta = start.T @ end
    angle = np.arccos(np.clip((np.trace(delta) - 1) / 2, -1, 1))
    if angle < 1e-8:
        return start.copy()
    if np.pi - angle < 1e-5:
        # The rotation axis is the eigenvector with eigenvalue one. Symmetrizing
        # avoids complex eigenvectors due to roundoff at a half turn.
        _, vectors = np.linalg.eigh((delta + delta.T) / 2)
        axis = vectors[:, -1]
        skew = np.array(
            [delta[2, 1] - delta[1, 2], delta[0, 2] - delta[2, 0], delta[1, 0] - delta[0, 1]]
        )
        if np.linalg.norm(skew) > 1e-10:
            axis *= 1 if axis @ skew >= 0 else -1
        elif axis[np.argmax(np.abs(axis))] < 0:
            axis *= -1
    else:
        axis = np.array(
            [delta[2, 1] - delta[1, 2], delta[0, 2] - delta[2, 0], delta[1, 0] - delta[0, 1]]
        ) / (2 * np.sin(angle))
    x, y, z = axis
    cross = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    value = phase * angle
    return start @ (np.eye(3) + np.sin(value) * cross + (1 - np.cos(value)) * cross @ cross)


def reach_arm(pose, skeleton, target, *, side="right", frames=61, hand_rotation=None):
    """Move the wrist while preserving its local pose or reaching a hand orientation.

    Reject unreachable targets instead of projecting them and declaring arrival.
    Finger articulation, joint limits, self-collision and object contact are not
    established here. Callers must qualify those before using this as a grasp.
    """
    import numpy as np

    if side not in ARMS or type(frames) is not int or not 2 <= frames <= 320:
        raise ValueError("Choose left/right and 2-320 frames at 20 Hz.")
    if (
        not isinstance(target, list)
        or len(target) != 3
        or any(type(value) not in (int, float) or not np.isfinite(value) for value in target)
    ):
        raise ValueError("Wrist target must be a finite XYZ position in metres.")
    if not isinstance(pose, dict) or not isinstance(pose.get("positions"), list):
        raise ValueError("Expected an observed Core pose.")
    points = np.asarray(pose["positions"], dtype=float)
    if points.shape != (27, 3):
        raise ValueError("Expected 27 joint positions.")
    validate_pose(pose, points[0, [0, 2]].tolist())
    rotations = np.asarray(pose["rotations"], dtype=float)
    if hand_rotation is not None:
        hand_rotation = np.asarray(hand_rotation, dtype=float)
        if (
            hand_rotation.shape != (3, 3)
            or not np.isfinite(hand_rotation).all()
            or not np.allclose(hand_rotation.T @ hand_rotation, np.eye(3), atol=1e-6)
            or abs(np.linalg.det(hand_rotation) - 1) > 1e-6
        ):
            raise ValueError("Hand orientation must be a proper global rotation matrix.")
    reconstructed = forward_positions(rotations, points[0], skeleton)
    if np.max(np.linalg.norm(reconstructed - points, axis=-1)) > 0.001:
        raise ValueError("Observed positions do not agree with the supplied Core skeleton.")
    names = skeleton["joint_names"]
    if len(names) != 27 or len(set(names)) != 27:
        raise ValueError("Expected unique Core joint names.")
    shoulder, elbow, wrist, hand_end = [names.index(name) for name in ARMS[side]]
    parents = skeleton["parents"]
    if [parents[elbow], parents[wrist], parents[hand_end]] != [shoulder, elbow, wrist]:
        raise ValueError("Unexpected Core arm hierarchy.")
    origin, middle, start = points[[shoulder, elbow, wrist]]
    upper = np.linalg.norm(middle - origin)
    lower = np.linalg.norm(start - middle)
    if min(upper, lower) < 1e-6:
        raise ValueError("Arm segments must have nonzero lengths.")
    target = np.asarray(target, dtype=float)
    limit = upper + lower
    distance = np.linalg.norm(target - origin)
    if not abs(upper - lower) + 1e-6 < distance < limit - 1e-6:
        raise ValueError(f"Wrist target outside geometric arm reach ({limit:.6f} m maximum).")
    positions, matrices = [points.copy()], [rotations.copy()]
    for index in range(1, frames):
        phase = index / (frames - 1)
        blend = phase * phase * (3 - 2 * phase)
        goal = start + (target - start) * blend
        direction = goal - origin
        distance = np.linalg.norm(direction)
        if not abs(upper - lower) + 1e-6 < distance < limit - 1e-6:
            raise ValueError("The wrist path passes through an unreachable arm configuration.")
        direction /= distance
        along = (upper * upper - lower * lower + distance * distance) / (2 * distance)
        bend = middle - origin - direction * ((middle - origin) @ direction)
        if np.linalg.norm(bend) < 1e-6:
            # Keep a deterministic bend plane when starting from an extended arm.
            bend = rotations[0] @ np.array([0.0, 0.0, 1.0])
            bend -= direction * (bend @ direction)
        if np.linalg.norm(bend) < 1e-6:
            raise ValueError("Cannot determine a continuous elbow bend plane.")
        bend /= np.linalg.norm(bend)
        desired = (
            origin + direction * along + bend * np.sqrt(max(0.0, upper * upper - along * along))
        )
        updated = rotations.copy()
        updated[shoulder] = between(middle - origin, desired - origin) @ rotations[shoulder]
        updated[elbow] = between(start - middle, goal - desired) @ rotations[elbow]
        actual = forward_positions(updated, points[0], skeleton)
        if np.linalg.norm(actual[wrist] - goal) > 1e-5:
            raise ValueError("Forward kinematics did not reach the requested wrist point.")
        positions.append(actual)
        matrices.append(updated)
    local_hand = rotations[elbow].T @ rotations[wrist]
    local_target = local_hand if hand_rotation is None else matrices[-1][elbow].T @ hand_rotation
    descendants = {wrist}
    for joint, parent in enumerate(parents):
        if parent in descendants:
            descendants.add(joint)
    for index in range(1, frames):
        phase = index / (frames - 1)
        blend = phase * phase * (3 - 2 * phase)
        updated = matrices[index]
        new_hand = updated[elbow] @ interpolate_rotation(local_hand, local_target, blend)
        change = new_hand @ rotations[wrist].T
        for joint in descendants:
            updated[joint] = change @ rotations[joint]
        positions[index] = forward_positions(updated, points[0], skeleton)
    return {
        "posed_joints": np.asarray(positions),
        "global_rot_mats": np.asarray(matrices),
        "fps": 20.0,
        "target": target,
        "wrist": wrist,
        "upper_arm_m": float(upper),
        "forearm_m": float(lower),
    }
