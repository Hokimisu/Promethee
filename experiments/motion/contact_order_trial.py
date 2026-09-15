"""Compare official foot correction after continuity, without relaxing runtime gates."""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
from ardy.constraints import FullBodyConstraintSet, Root2DConstraintSet
from ardy.postprocess import post_process_motion
from ardy.skeleton.definitions import CoreSkeleton27
from ardy.viz.core_skin import CoreSkin

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from promethee.ardy_geometry import ground_motion  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", choices=("endpoint", "trajectory"), default="endpoint")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    request = json.loads(args.request.read_text())
    job = request["job"]
    path = args.request.with_name(job["job_id"] + "-processed.npz")
    with np.load(path, allow_pickle=False) as data:
        values = {key: data[key].copy() for key in data.files}
    skeleton = CoreSkeleton27()
    skin = CoreSkin(skeleton)
    count = len(values["posed_joints"])
    positions = torch.from_numpy(values["posed_joints"])
    rotations = torch.from_numpy(values["global_rot_mats"])
    indices = torch.tensor([count - 1]) if args.root == "endpoint" else torch.arange(count)
    roots = (
        torch.tensor([job["target"]], dtype=torch.float32)
        if args.root == "endpoint"
        else torch.from_numpy(values["root_positions"][:, [0, 2]])
    )
    constraints = [
        FullBodyConstraintSet(skeleton, torch.tensor([0]), positions[:1], rotations[:1]),
        Root2DConstraintSet(skeleton, indices, roots),
    ]
    corrected = post_process_motion(
        torch.from_numpy(values["local_rot_mats"])[None],
        torch.from_numpy(values["root_positions"])[None],
        torch.from_numpy(values["foot_contacts"])[None],
        skeleton,
        constraint_lst=constraints,
    )
    values.update({key: value[0].numpy() for key, value in corrected.items()})
    grounding = ground_motion(values, skin)
    np.savez(args.output / "corrected.npz", **values)
    joints = values["posed_joints"]
    contact = values["foot_contacts"] > 0.5
    pairs = contact[1:] & contact[:-1]
    foot_speed = (
        np.linalg.norm(np.diff(joints[:, [25, 26, 21, 22]][:, :, [0, 2]], axis=0), axis=-1) * 20
    )
    active = foot_speed[pairs]
    summary = {
        "source": str(path),
        "root_constraint": args.root,
        "grounding": grounding,
        "first_pose_error_m": float(
            np.linalg.norm(joints[0] - job["start_pose"]["positions"], axis=-1).max()
        ),
        "target_error_m": float(np.linalg.norm(joints[-1, 0, [0, 2]] - job["target"])),
        "max_joint_step_m": float(np.linalg.norm(np.diff(joints, axis=0), axis=-1).max()),
        "max_predicted_contact_speed_m_s": float(active.max()) if active.size else None,
        "p95_predicted_contact_speed_m_s": float(np.percentile(active, 95))
        if active.size
        else None,
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2))
    (args.output / "trial-source.py").write_text(Path(__file__).read_text())
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
