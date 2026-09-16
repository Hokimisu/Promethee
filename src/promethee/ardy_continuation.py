"""ARDY-side history reconstruction and one-horizon generation (Python 3.11)."""

import hashlib
import io


def generation_window(history_frames, future_frames):
    """Match Core20's ten-second context budget without pulling a distant goal closer."""
    total = history_frames + future_frames
    return min(total, 200), total - 1 if total <= 200 else None


class ActionTextEncoding:
    """One encoding for one action in one fixed worker/model lifetime."""

    def __init__(self, model):
        self.model = model
        self.stream_id = self.text = self.encoding = None

    def get(self, stream_id, text):
        if self.stream_id == stream_id:
            if self.text != text:
                raise ValueError("A motion stream cannot change its text without a new identity.")
            return self.encoding, True
        self.encoding = self.model._encode_text([text])
        self.stream_id, self.text = stream_id, text
        return self.encoding, False


def read_history(output, job):
    import numpy as np

    descriptor = job["history"]
    if descriptor is None:
        return None
    if set(descriptor) != {"file", "sha256", "frames", "executed_frames", "committed_frames"}:
        raise ValueError("Invalid history descriptor.")
    count = descriptor["frames"]
    if (
        type(count) is not int
        or not 4 <= count <= 160
        or count % 4
        or any(
            type(descriptor[k]) is not int or descriptor[k] < 0
            for k in ("executed_frames", "committed_frames")
        )
        or descriptor["executed_frames"] + descriptor["committed_frames"] != count
        or descriptor["file"] != f"{job['job_id']}-history.npz"
    ):
        raise ValueError("Invalid history range or filename.")
    path = output / descriptor["file"]
    with path.open("rb") as stream:
        payload = stream.read(1024 * 1024 + 1)
    if len(payload) > 1024 * 1024 or hashlib.sha256(payload).hexdigest() != descriptor["sha256"]:
        raise ValueError("History file differs from the submitted context.")
    with np.load(io.BytesIO(payload), allow_pickle=False) as archive:
        points = archive["posed_joints"].copy()
        rotations = archive["global_rot_mats"].copy()
        if float(archive["fps"]) != 20:
            raise ValueError("History cadence must be 20 Hz.")
    if (
        points.shape != (count, 27, 3)
        or rotations.shape != (count, 27, 3, 3)
        or not np.isfinite(points).all()
        or not np.isfinite(rotations).all()
    ):
        raise ValueError("Invalid Core history arrays.")
    start = job["start_pose"]
    if start is None or not (
        np.allclose(points[-1], start["positions"], atol=1e-6, rtol=0)
        and np.allclose(rotations[-1], start["rotations"], atol=1e-6, rtol=0)
    ):
        raise ValueError("History does not end at the committed starting pose.")
    return {"posed_joints": points, "global_rot_mats": rotations, "root_positions": points[:, 0]}


def encode_history(model, values):
    """Rebuild features from corrected poses; never feed stale generation latents."""
    import torch

    matrices = torch.as_tensor(values["global_rot_mats"], device=model.device).unsqueeze(0)
    root = torch.as_tensor(values["root_positions"], device=model.device).unsqueeze(0)
    local = matrices.clone()
    for joint, parent in enumerate(model.skeleton.joint_parents.tolist()):
        if parent >= 0:
            local[:, :, joint] = matrices[:, :, parent].transpose(-1, -2) @ matrices[:, :, joint]
    encoded = model.motion_rep(local_joint_rots=local, root_positions=root, to_normalize=True)
    restored = model.motion_rep.inverse(encoded, is_normalized=True)
    expected = torch.as_tensor(values["posed_joints"], device=model.device)
    error = torch.linalg.vector_norm(restored["posed_joints"][0] - expected, dim=-1).max().item()
    if not torch.isfinite(encoded).all() or not error <= 0.002:
        raise ValueError(f"History reconstruction changes corrected joints by {error:.6f} m.")
    return encoded, error


def generate_chunk(model, job, history, goal_skin, text_encoding):
    import numpy as np
    import torch
    from ardy.constraints import FullBodyConstraintSet, Root2DConstraintSet
    from ardy.motion_rep.tools import compute_heading_angle
    from ardy_geometry import posture_goal

    if model.gen_horizon_len != 40 or model.num_frames_per_token != 4:
        raise ValueError("Continuous playback requires Core Horizon40 and four-frame tokens.")
    remaining = job["future_frames"]
    if type(remaining) is not int or remaining not in range(40, 321, 40) or job["frames"] != 40:
        raise ValueError("Continuous requests emit 40 poses with 40-320 future poses remaining.")
    encoded, error = encode_history(model, history) if history is not None else (None, None)
    history_length = 0 if history is None else len(history["posed_joints"])
    window, target_frame = generation_window(history_length, remaining)
    target = torch.tensor([job["target"]], device=model.device)
    constraints = (
        [Root2DConstraintSet(model.skeleton, torch.tensor([target_frame]), target)]
        if target_frame is not None
        else []
    )
    points = torch.tensor(job["start_pose"]["positions"], device=model.device).unsqueeze(0)
    rotations = torch.tensor(job["start_pose"]["rotations"], device=model.device).unsqueeze(0)
    heading = compute_heading_angle(points.unsqueeze(0), model.skeleton)[:, 0]
    if history is None:
        constraints.append(
            FullBodyConstraintSet(model.skeleton, torch.tensor([0]), points, rotations)
        )
    if job["posture"] is not None and target_frame is not None:
        goal_points, goal_rotations = posture_goal(
            model.skeleton,
            goal_skin,
            rotations,
            points,
            float(heading[0]),
            job["target"],
            job["posture"],
        )
        constraints.append(
            FullBodyConstraintSet(
                model.skeleton, torch.tensor([target_frame]), goal_points, goal_rotations
            )
        )
    observed, mask = model.motion_rep.create_conditions_from_constraints_batched(
        constraints,
        torch.tensor([window], device=model.device),
        to_normalize=True,
        device=model.device,
    )
    generated = model.autoregressive_step(
        num_frames=window,
        num_denoising_steps=10,
        motion_mask=mask,
        observed_motion=observed,
        text_feat=text_encoding[0],
        text_pad_mask=text_encoding[1],
        cfg_weight=(2.0, 2.0),
        init_history_sequence=encoded,
        init_first_heading_angle=heading,
    )
    decoded = model.motion_rep.inverse(generated, is_normalized=True)
    raw = {key: value[0, history_length:].cpu().numpy() for key, value in decoded.items()}
    if len(raw["posed_joints"]) != 40 or any(not np.isfinite(x).all() for x in raw.values()):
        raise ValueError("Invalid autoregressive output horizon.")
    return raw, {
        "history_frames": history_length,
        "history_roundtrip_error_m": error,
        "window_frames": window,
        "target_frame": target_frame,
    }
