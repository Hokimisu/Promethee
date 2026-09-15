"""Diagnostic comparison: fade a pose-space start offset into raw ARDY motion."""

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from ardy.geometry import axis_angle_to_matrix, matrix_to_axis_angle
from ardy.postprocess import post_process_motion
from ardy.skeleton.definitions import CoreSkeleton27
from ardy.viz.core_skin import CoreSkin


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--correct-feet", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    request = json.loads(args.request.read_text())
    job = request["job"]
    with np.load(args.request.with_name(job["job_id"] + "-raw.npz"), allow_pickle=False) as data:
        values = {key: data[key].copy() for key in data.files}
    skeleton = CoreSkeleton27()
    skin = CoreSkin(skeleton)
    if args.correct_feet:
        corrected = post_process_motion(
            torch.from_numpy(values["local_rot_mats"])[None],
            torch.from_numpy(values["root_positions"])[None],
            torch.from_numpy(values["foot_contacts"])[None],
            skeleton,
        )
        values.update({key: value[0].numpy() for key, value in corrected.items()})
    local = torch.from_numpy(values["local_rot_mats"]).clone()
    root = torch.from_numpy(values["root_positions"]).clone()
    initial = job["start_pose"]
    initial_rotations = torch.tensor(initial["rotations"]).unsqueeze(0)
    initial_local = skeleton.global_rots_to_local_rots(initial_rotations)[0]
    delta = initial_local @ local[0].transpose(-1, -2)
    delta_angle = matrix_to_axis_angle(delta)
    frames = min(16, len(local))
    t = torch.linspace(0, 1, frames)
    weight = 1 - (3 * t * t - 2 * t * t * t)
    correction = axis_angle_to_matrix(delta_angle[None] * weight[:, None, None])
    local[:frames] = correction @ local[:frames]
    root[:frames] += weight[:, None] * (torch.tensor(initial["positions"][0]) - root[0].clone())
    matrices, points, _ = skeleton.fk(local, root)
    lifts = []
    with torch.inference_mode():
        for p, r in zip(points, matrices, strict=True):
            mesh = skin.skin(r[None], p[None], rot_is_global=True)
            lifts.append(max(0.0, -float(mesh[..., 1].min())))
    lift = torch.tensor(lifts)
    points[:, :, 1] += lift[:, None]
    root[:, 1] += lift
    values.update(
        posed_joints=points.numpy(),
        global_rot_mats=matrices.numpy(),
        local_rot_mats=local.numpy(),
        root_positions=root.numpy(),
    )
    np.savez(args.output / "inertial.npz", **values)
    step = np.linalg.norm(np.diff(points.numpy(), axis=0), axis=-1)
    summary = {
        "request": str(args.request),
        "fade_frames": frames,
        "max_lift_m": max(lifts),
        "max_lift_step_m": float(np.abs(np.diff(lifts)).max()),
        "max_joint_step_m": float(step.max()),
        "first_pose_error_m": float(
            np.linalg.norm(points[0].numpy() - initial["positions"], axis=-1).max()
        ),
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
