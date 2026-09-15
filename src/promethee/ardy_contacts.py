"""Kinematic Core leg correction; preserves bone lengths and reports unreachable targets."""


def between(a, b):
    import numpy as np

    if min(np.linalg.norm(a), np.linalg.norm(b)) < 1e-8:
        raise ValueError("Cannot align a zero-length bone.")
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    v, c = np.cross(a, b), float(np.clip(a @ b, -1, 1))
    if c < -0.999999:
        axis = np.cross(a, np.eye(3)[np.argmin(np.abs(a))])
        axis /= np.linalg.norm(axis)
        return 2 * np.outer(axis, axis) - np.eye(3)
    x, y, z = v
    skew = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return np.eye(3) + skew + skew @ skew / (1 + c)


def solve_leg(points, rotations, indices, target, foot_rotation):
    import numpy as np

    hip, knee, ankle, toe = indices
    a, b, c = points[[hip, knee, ankle]]
    first, second = np.linalg.norm(b - a), np.linalg.norm(c - b)
    if min(first, second) < 1e-6:
        raise ValueError("Cannot solve a zero-length leg segment.")
    direction = target - a
    distance = np.linalg.norm(direction)
    if distance < 1e-8:
        direction = c - a
        if np.linalg.norm(direction) < 1e-8:
            direction = b - a
    direction /= np.linalg.norm(direction)
    reachable = np.clip(distance, abs(first - second) + 1e-5, first + second - 1e-5)
    projected = a + direction * reachable
    along = (first * first - second * second + reachable * reachable) / (2 * reachable)
    bend = b - a - direction * ((b - a) @ direction)
    if np.linalg.norm(bend) < 1e-5:
        bend = rotations[hip] @ np.array([0.0, 0.0, 1.0])
        bend -= direction * (bend @ direction)
    if np.linalg.norm(bend) < 1e-5:
        bend = np.eye(3)[np.argmin(np.abs(direction))]
        bend -= direction * (bend @ direction)
    bend /= max(np.linalg.norm(bend), 1e-8)
    desired_knee = a + direction * along + bend * np.sqrt(max(0, first * first - along * along))
    result = rotations.copy()
    result[hip] = between(b - a, desired_knee - a) @ rotations[hip]
    result[knee] = between(c - b, projected - desired_knee) @ rotations[knee]
    result[ankle] = foot_rotation
    result[toe] = foot_rotation @ rotations[ankle].T @ rotations[toe]
    return result, float(np.linalg.norm(projected - target))


def stabilize_contacts(values, skeleton):
    """Anchor predicted heel/toe support, preserving root and actual segment lengths.

    The model still supplies the gait, torso, arms and swing rotations. This is
    kinematic IK, not a physical contact solver. Unreachable targets are projected
    onto the leg's reachable sphere and their maximum residual is returned. The
    normal runtime gates must assess the corrected FK trajectory, not the targets.
    """
    import numpy as np
    import torch

    positions = values["posed_joints"].astype(np.float64)
    raw_rotations = values["global_rot_mats"].astype(np.float64)
    rotations = raw_rotations.copy()
    residuals = []
    for names, slots in (
        (("LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase"), (0, 1)),
        (("RightUpLeg", "RightLeg", "RightFoot", "RightToeBase"), (2, 3)),
    ):
        indices = [skeleton.bone_index[name] for name in names]
        _, _, ankle, toe = indices
        neutral = skeleton.neutral_joints.numpy()
        offset = (neutral[toe] - neutral[ankle]).astype(np.float64)
        anchors = [None, None]
        last_delta, applied_delta, flight = np.zeros(3), np.zeros(3), 8
        for t in range(len(positions)):
            contact = values["foot_contacts"][t, list(slots)] > 0.5
            r = raw_rotations[t, ankle].copy()
            raw = positions[t, ankle]
            if contact.any():
                flight = 0
                for j, active in enumerate(contact):
                    if not active:
                        anchors[j] = None
                for j, active in enumerate(contact):
                    if active and anchors[j] is None:
                        if anchors[1 - j] is not None:
                            anchors[j] = anchors[1 - j] + (1 if j else -1) * (r @ offset)
                        else:
                            anchors[j] = raw + applied_delta + (r @ offset if j else 0)
                if contact.all():
                    r = between(r @ offset, anchors[1] - anchors[0]) @ r
                target = anchors[0] if contact[0] else anchors[1] - r @ offset
                last_delta = target - raw
            else:
                anchors = [None, None]
                flight = min(8, flight + 1)
                phase = flight / 8
                target = raw + last_delta * (1 - (3 * phase**2 - 2 * phase**3))
            updated, residual = solve_leg(positions[t], rotations[t], indices, target, r)
            applied_delta = target - raw
            rotations[t] = updated
            residuals.append(residual)
    local = skeleton.global_rots_to_local_rots(torch.from_numpy(rotations.astype(np.float32)))
    matrices, points, _ = skeleton.fk(local, torch.from_numpy(values["root_positions"]))
    values.update(
        local_rot_mats=local.numpy(), global_rot_mats=matrices.numpy(), posed_joints=points.numpy()
    )
    return max(residuals)


def sole_contact_metrics(sole, fps=20):
    """Separate geometric surface contact from mere proximity to the floor.

    A 0.1 mm symmetric tolerance absorbs float32 skinning roundoff (observed
    below 1e-8 m), without classifying a foot flying 2 mm above the plane as
    contact. The old 5 mm proximity statistic remains visible for diagnostics.
    Neither statistic establishes a physical support force or balance.
    """
    import numpy as np

    sole = np.asarray(sole)
    if sole.ndim != 3 or sole.shape[-1] != 3 or len(sole) < 2 or not np.isfinite(sole).all():
        raise ValueError("Expected a finite sequence of foot mesh vertices.")
    if not np.isfinite(fps) or fps <= 0:
        raise ValueError("Expected a positive frame rate.")
    surface = np.abs(sole[:, :, 1]) <= 0.0001
    contact = surface[:-1] & surface[1:]
    near = (sole[:-1, :, 1] <= 0.005) & (sole[1:, :, 1] <= 0.005)
    speed = np.linalg.norm(np.diff(sole[..., [0, 2]], axis=0), axis=-1) * fps
    sliding = speed[contact]
    nearby = speed[near]
    return {
        "contact_tolerance_m": 0.0001,
        "vertex_contact_pairs": int(contact.sum()),
        "frames_with_surface_contact": int(surface.any(axis=1).sum()),
        "frame_pairs_with_surface_contact": int(contact.any(axis=1).sum()),
        "frames": len(sole),
        "minimum_foot_height_m": float(sole[..., 1].min()),
        "maximum_lowest_foot_height_m": float(sole[..., 1].min(axis=1).max()),
        "speed_max_m_s": float(sliding.max()) if len(sliding) else None,
        "speed_p95_m_s": float(np.quantile(sliding, 0.95)) if len(sliding) else None,
        "near_floor_tolerance_m": 0.005,
        "near_floor_pairs": int(near.sum()),
        "near_floor_speed_max_m_s": float(nearby.max()) if len(nearby) else None,
        "near_floor_speed_p95_m_s": float(np.quantile(nearby, 0.95)) if len(nearby) else None,
    }


def validate_sole_contacts(metrics):
    if not metrics["vertex_contact_pairs"]:
        raise ValueError("No geometric foot contact could be verified.")
    if metrics["speed_max_m_s"] > 0.2 or metrics["speed_p95_m_s"] > 0.05:
        raise ValueError(
            "Foot mesh slides beyond the geometric contact limits "
            f"(max={metrics['speed_max_m_s']:.6f}, p95={metrics['speed_p95_m_s']:.6f} m/s)."
        )


def measure_skin_contacts(values, skin):
    import numpy as np
    import torch

    indices = skin.lbs_indices.numpy()
    weights = skin.lbs_weights.numpy()
    feet = (np.isin(indices, [21, 22, 25, 26]) * weights).sum(axis=-1) > 0.5
    sole = []
    with torch.inference_mode():
        for points, rotations in zip(
            values["posed_joints"], values["global_rot_mats"], strict=True
        ):
            vertices = skin.skin(
                torch.from_numpy(rotations[None]),
                torch.from_numpy(points[None]),
                rot_is_global=True,
            )
            sole.append(vertices[0].numpy()[feet])
    return sole_contact_metrics(np.asarray(sole))
