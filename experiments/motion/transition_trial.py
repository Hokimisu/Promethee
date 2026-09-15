"""T07 experiment: constrain the next motion to the actually observed previous pose."""

import argparse
import json
import math
import shutil
from pathlib import Path

import numpy as np
import torch
from ardy.constraints import FullBodyConstraintSet, Root2DConstraintSet
from ardy.model.load_model import load_model, load_text_encoder
from ardy.motion_rep.tools import compute_heading_angle, length_to_mask
from ardy.postprocess import post_process_motion
from ardy.tools import seed_everything
from ardy.viz.core_skin import CoreSkin
from qualify import arrays, sync_time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-motion", type=Path, required=True)
    parser.add_argument("--target", type=float, nargs=2, required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint-root", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--end-posture", choices=["standing", "arms_raised"])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, args.output / "trial-source.py")
    model = load_model(
        "core", device="cuda", text_encoder=False, checkpoints_dir=args.checkpoint_root
    )
    model.text_encoder = load_text_encoder(mode="api", url="http://127.0.0.1:9550", device="cuda")
    seed_everything(args.seed)
    with np.load(args.from_motion, allow_pickle=False) as data:
        initial = data["posed_joints"][-1].copy()
        rotations = torch.tensor(data["global_rot_mats"][-1:], device="cuda")
    offset = initial[0].copy()
    offset[1] = 0
    local = torch.tensor(initial - offset, device="cuda").unsqueeze(0)
    heading = compute_heading_angle(local.unsqueeze(0), model.skeleton)[:, 0]
    constraints = [
        FullBodyConstraintSet(model.skeleton, torch.tensor([0]), local, rotations),
        Root2DConstraintSet(
            model.skeleton,
            torch.tensor([119]),
            torch.tensor(
                np.asarray(args.target) - offset[[0, 2]], device="cuda", dtype=torch.float32
            ).unsqueeze(0),
        ),
    ]
    if args.end_posture:
        local_rotations = model.skeleton.global_rots_to_local_rots(rotations.clone())
        angle = float(heading[0])
        c, s = math.cos(angle), math.sin(angle)
        yaw_rotation = torch.tensor([[c, 0, s], [0, 1, 0], [-s, 0, c]], device="cuda")
        direction = 1 if args.end_posture == "arms_raised" else -1
        for name, sign in (("RightArm", -1), ("LeftArm", 1)):
            angle = direction * sign * math.pi / 2
            c, s = math.cos(angle), math.sin(angle)
            arm_rotation = yaw_rotation @ torch.tensor(
                [[c, -s, 0], [s, c, 0], [0, 0, 1]], device="cuda"
            )
            index = model.skeleton.bone_index[name]
            parent = int(model.skeleton.joint_parents[index])
            local_rotations[0, index] = rotations[0, parent].T @ arm_rotation
        for name in ("RightForeArm", "LeftForeArm", "RightHand", "LeftHand"):
            local_rotations[0, model.skeleton.bone_index[name]] = torch.eye(3, device="cuda")
        target = np.asarray(args.target) - offset[[0, 2]]
        goal_rotations, goal_points, _ = model.skeleton.fk(
            local_rotations,
            torch.tensor(
                [[target[0], initial[0, 1], target[1]]], device="cuda", dtype=torch.float32
            ),
        )
        mesh = CoreSkin(model.skeleton).skin(goal_rotations, goal_points, rot_is_global=True)
        goal_points[:, :, 1] -= mesh[..., 1].min()
        constraints.append(
            FullBodyConstraintSet(model.skeleton, torch.tensor([119]), goal_points, goal_rotations)
        )
        np.savez(
            args.output / "goal.npz",
            posed_joints=goal_points.cpu().numpy(),
            global_rot_mats=goal_rotations.cpu().numpy(),
        )
    lengths = torch.tensor([120], device="cuda")
    observed, mask = model.motion_rep.create_conditions_from_constraints_batched(
        constraints, lengths, to_normalize=True, device="cuda"
    )
    start = sync_time()
    with torch.inference_mode():
        motion = model(
            [args.prompt],
            120,
            10,
            length_to_mask(lengths),
            heading,
            mask,
            observed,
            cfg_weight=(2.0, 2.0),
            crop_history_length=160,
            progress_bar=lambda values: values,
        )
        output = model.motion_rep.inverse(motion, is_normalized=True)
    elapsed = sync_time() - start
    raw = arrays(output)
    output.update(
        post_process_motion(
            output["local_rot_mats"],
            output["root_positions"],
            output["foot_contacts"],
            model.skeleton,
            constraint_lst=constraints,
        )
    )
    processed = arrays(output)
    measures = {
        "seed": args.seed,
        "prompt": args.prompt,
        "end_posture": args.end_posture,
        "generation_with_text_seconds": elapsed,
    }
    for name, values in (("raw", raw), ("processed", processed)):
        for field in ("root_positions", "posed_joints"):
            values[field] += offset
        joints = values["posed_joints"][0]
        feet = joints[:, model.skeleton.foot_joint_idx]
        measures[name] = {
            "max_initial_joint_error_m": float(np.linalg.norm(joints[0] - initial, axis=-1).max()),
            "target_error_m": float(np.linalg.norm(joints[-1, 0, [0, 2]] - args.target)),
            "lowest_foot_joint_y_m": float(feet[:, :, 1].min()),
            "max_joint_frame_step_m": float(np.linalg.norm(np.diff(joints, axis=0), axis=-1).max()),
        }
        np.savez(
            args.output / f"{name}.npz",
            **{k: v[0] for k, v in values.items()},
            fps=np.asarray(20),
            text=np.asarray(args.prompt),
        )
    (args.output / "measurements.json").write_text(json.dumps(measures, indent=2))
    print(json.dumps(measures), flush=True)


if __name__ == "__main__":
    main()
