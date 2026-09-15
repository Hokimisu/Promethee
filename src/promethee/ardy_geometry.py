"""Core-specific geometric constraints, imported only inside the ARDY environment."""

import math


def floor_lift_envelope(required, max_step=0.015):
    """Smallest nonnegative lift envelope meeting a per-frame rate bound."""
    values = list(required)
    if not values or not math.isfinite(max_step) or max_step <= 0:
        raise ValueError("A nonempty lift sequence and positive step limit are required.")
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("Required lifts must be finite and nonnegative.")
    for index in range(1, len(values)):
        values[index] = max(values[index], values[index - 1] - max_step)
    for index in range(len(values) - 2, -1, -1):
        values[index] = max(values[index], values[index + 1] - max_step)
    return values


def continue_from_pose(values, initial, skeleton, fade_frames=16):
    """Fade the initial local-rotation/root error into the original ARDY trajectory.

    Only the first 0.8 seconds are adjusted; FK retains the actual bone lengths.
    This is motion postprocessing, not a replacement animation or a physical solver.
    """
    import torch
    from ardy.geometry import axis_angle_to_matrix, matrix_to_axis_angle

    if initial is None:
        return
    local = torch.from_numpy(values["local_rot_mats"]).clone()
    root = torch.from_numpy(values["root_positions"]).clone()
    initial_local = skeleton.global_rots_to_local_rots(torch.tensor(initial["rotations"])[None])[0]
    delta = initial_local @ local[0].transpose(-1, -2)
    delta_angle = matrix_to_axis_angle(delta)
    count = min(fade_frames, len(local))
    t = torch.linspace(0, 1, count)
    weight = 1 - (3 * t * t - 2 * t * t * t)
    local[:count] = axis_angle_to_matrix(delta_angle[None] * weight[:, None, None]) @ local[:count]
    root[:count] += weight[:, None] * (torch.tensor(initial["positions"][0]) - root[0].clone())
    matrices, points, _ = skeleton.fk(local, root)
    values.update(
        local_rot_mats=local.numpy(),
        root_positions=root.numpy(),
        global_rot_mats=matrices.numpy(),
        posed_joints=points.numpy(),
    )


def posture_goal(skeleton, skin, initial_rotations, initial_positions, heading, target, name):
    """Change the arms while retaining the observed torso and leg configuration."""
    import torch

    if name not in {"standing", "arms_raised"}:
        raise ValueError("Unknown posture constraint.")
    device = initial_rotations.device
    local = skeleton.global_rots_to_local_rots(initial_rotations.clone())
    c, s = math.cos(heading), math.sin(heading)
    yaw = torch.tensor([[c, 0, s], [0, 1, 0], [-s, 0, c]], device=device)
    direction = 1 if name == "arms_raised" else -1
    for joint_name, sign in (("RightArm", -1), ("LeftArm", 1)):
        angle = direction * sign * math.pi / 2
        c, s = math.cos(angle), math.sin(angle)
        rotation = yaw @ torch.tensor([[c, -s, 0], [s, c, 0], [0, 0, 1]], device=device)
        index = skeleton.bone_index[joint_name]
        parent = int(skeleton.joint_parents[index])
        local[0, index] = initial_rotations[0, parent].T @ rotation
    for joint_name in ("RightForeArm", "LeftForeArm", "RightHand", "LeftHand"):
        local[0, skeleton.bone_index[joint_name]] = torch.eye(3, device=device)
    rotations, points, _ = skeleton.fk(
        local,
        torch.tensor(
            [[target[0], float(initial_positions[0, 0, 1]), target[1]]],
            device=device,
            dtype=torch.float32,
        ),
    )
    mesh = skin.skin(rotations, points, rot_is_global=True)
    points[:, :, 1] -= mesh[..., 1].min()
    return points, rotations


def ground_motion(values, skin):
    """Lift whole poses only enough to clear the actual skin; preserve XZ and rotations.

    `values` contains one unbatched trajectory, modified in place. The caller saves
    the original separately. This does not solve balance or horizontal sliding.
    """
    import numpy as np
    import torch

    points, rotations = values["posed_joints"], values["global_rot_mats"]
    lifts = []
    with torch.inference_mode():
        for joints, matrices in zip(points, rotations, strict=True):
            mesh = skin.skin(
                torch.from_numpy(matrices[None]), torch.from_numpy(joints[None]), rot_is_global=True
            )
            lifts.append(max(0.0, -float(mesh[..., 1].min())))
    lift = np.asarray(floor_lift_envelope(lifts), dtype=points.dtype)
    if not np.isfinite(lift).all() or lift.max() > 0.05:
        raise ValueError("Required floor correction exceeds the calibrated 5 cm envelope.")
    points[:, :, 1] += lift[:, None]
    values["root_positions"][:, 1] += lift
    return {
        "max_lift_m": float(lift.max()),
        "first_lift_m": float(lift[0]),
        "max_lift_step_m": float(np.abs(np.diff(lift)).max()) if len(lift) > 1 else 0.0,
        "method": "positive-Y whole-body Core mesh-floor projection with 15 mm/frame envelope",
    }
