"""Standalone Python 3.11 ARDY worker. Not imported by the CPU application.

stdin/stdout carry bounded JSON messages; model logs go to stderr. Numeric motion
files remain in the private output directory and are never written into SQLite.
"""

import argparse
import contextlib
import json
import os
import re
import sys
import time
from pathlib import Path


def serve(args, send):
    send({"type": "started", "pid": os.getpid()})
    import numpy as np
    import torch
    from ardy.constraints import FullBodyConstraintSet, Root2DConstraintSet
    from ardy.model.load_model import load_model, load_text_encoder
    from ardy.motion_rep.tools import compute_heading_angle, length_to_mask
    from ardy.skeleton.definitions import CoreSkeleton27
    from ardy.tools import seed_everything
    from ardy.viz.core_skin import CoreSkin
    from ardy_contacts import measure_skin_contacts, stabilize_contacts, validate_sole_contacts
    from ardy_geometry import continue_from_pose, ground_motion, posture_goal

    args.output.mkdir(parents=True, exist_ok=True)
    model = load_model(
        "core", device="cuda", text_encoder=False, checkpoints_dir=args.checkpoint_root
    )
    model.text_encoder = load_text_encoder(mode="api", url=args.encoder_url, device="cuda")
    cpu_skin = CoreSkin(CoreSkeleton27())
    goal_skin = CoreSkin(model.skeleton)
    send(
        {
            "type": "ready",
            "skeleton": {
                "skeleton": model.skeleton.name,
                "joint_names": model.skeleton.bone_order_names,
                "parents": model.skeleton.joint_parents.tolist(),
                "neutral_joints": model.skeleton.neutral_joints.tolist(),
                "feet": model.skeleton.foot_joint_names,
                "fps": 20,
            },
        }
    )
    while True:
        line = sys.stdin.readline(65537)
        if not line:
            return
        if len(line) > 65536 or not line.endswith("\n"):
            raise ValueError("Oversized worker request.")
        job = json.loads(line)
        if job == {"type": "shutdown"}:
            return
        job_id = job.get("job_id")
        if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise ValueError("Invalid worker job ID.")
        try:
            if set(job) != {"job_id", "target", "text", "seed", "frames", "start_pose", "posture"}:
                raise ValueError("Invalid worker request fields.")
            frames, seed, text = job["frames"], job["seed"], job["text"]
            if type(frames) is not int or not 40 <= frames <= 320 or frames % 4:
                raise ValueError("Use 40 to 320 frames in multiples of four.")
            if type(seed) is not int or not 0 <= seed < 2**31:
                raise ValueError("Invalid seed.")
            if not isinstance(text, str) or not 1 <= len(text) <= 1000:
                raise ValueError("Invalid motion text.")
            target = np.asarray(job["target"], dtype=np.float32)
            if target.shape != (2,) or not np.isfinite(target).all() or (abs(target) > 5).any():
                raise ValueError("Invalid target.")
            initial = None
            constraints = []
            if job["start_pose"] is not None:
                initial = np.asarray(job["start_pose"]["positions"], dtype=np.float32)
                rotations = np.asarray(job["start_pose"]["rotations"], dtype=np.float32)
                if (
                    initial.shape != (27, 3)
                    or rotations.shape != (27, 3, 3)
                    or not np.isfinite(initial).all()
                    or not np.isfinite(rotations).all()
                ):
                    raise ValueError("Invalid starting pose.")
                offset = initial[0].copy()
                offset[1] = 0
                local = torch.tensor(initial - offset, device="cuda").unsqueeze(0)
                heading = compute_heading_angle(local.unsqueeze(0), model.skeleton)[:, 0]
                # All constraint indices stay on CPU: FullBodyConstraintSet creates
                # CPU joint indices internally, and ARDY concatenates indices before transfer.
                constraints.append(
                    FullBodyConstraintSet(
                        model.skeleton,
                        torch.tensor([0]),
                        local,
                        torch.tensor(rotations, device="cuda").unsqueeze(0),
                    )
                )
                if job["posture"] is not None:
                    goal_points, goal_rotations = posture_goal(
                        model.skeleton,
                        goal_skin,
                        torch.tensor(rotations, device="cuda").unsqueeze(0),
                        local,
                        float(heading[0]),
                        (target - offset[[0, 2]]).tolist(),
                        job["posture"],
                    )
                    constraints.append(
                        FullBodyConstraintSet(
                            model.skeleton, torch.tensor([frames - 1]), goal_points, goal_rotations
                        )
                    )
            else:
                offset = np.asarray([target[0], 0, target[1]], dtype=np.float32)
                heading = torch.zeros(1, device="cuda")
                constraints.append(
                    Root2DConstraintSet(
                        model.skeleton, torch.tensor([0]), torch.zeros((1, 2), device="cuda")
                    )
                )
            constraints.append(
                Root2DConstraintSet(
                    model.skeleton,
                    torch.tensor([frames - 1]),
                    torch.tensor(target - offset[[0, 2]], device="cuda").unsqueeze(0),
                )
            )
            lengths = torch.tensor([frames], device="cuda")
            observed, mask = model.motion_rep.create_conditions_from_constraints_batched(
                constraints, lengths, to_normalize=True, device="cuda"
            )
            seed_everything(seed)
            started = time.perf_counter()
            with torch.inference_mode():
                motion = model(
                    [text],
                    frames,
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
                raw = {key: value[0].detach().cpu().numpy() for key, value in output.items()}
            for field in ("root_positions", "posed_joints"):
                raw[field] += offset
            processed = {key: value.copy() for key, value in raw.items()}
            contact_residual = None
            for label, values in (("raw", raw), ("processed", processed)):
                if not all(np.isfinite(value).all() for value in values.values()):
                    raise ValueError("Non-finite generated motion.")
                if label == "processed":
                    continue_from_pose(values, job["start_pose"], cpu_skin.skeleton)
                    if initial is not None and job["posture"] is None:
                        contact_residual = stabilize_contacts(values, cpu_skin.skeleton)
                    grounding = ground_motion(values, cpu_skin, settle=job["posture"] is not None)
                with (args.output / f"{job_id}-{label}.npz").open("xb") as stream:
                    np.savez(
                        stream,
                        **values,
                        fps=np.asarray(20),
                        text=np.asarray(text),
                        seed=np.asarray(seed),
                    )
            joints = processed["posed_joints"]
            skin_contacts = measure_skin_contacts(processed, cpu_skin)
            (args.output / f"{job_id}-contacts.json").write_text(
                json.dumps(skin_contacts, indent=2, allow_nan=False), encoding="utf-8"
            )
            if initial is not None:
                validate_sole_contacts(skin_contacts)
            send(
                {
                    "type": "generated",
                    "job_id": job_id,
                    "file": f"{job_id}-processed.npz",
                    "elapsed_seconds": time.perf_counter() - started,
                    "grounding": grounding,
                    "skin_contacts": skin_contacts,
                    "max_unreachable_foot_target_m": contact_residual,
                    "max_start_error_m": (
                        float(np.linalg.norm(joints[0] - initial, axis=-1).max())
                        if initial is not None
                        else None
                    ),
                    "target_error_m": float(np.linalg.norm(joints[-1, 0, [0, 2]] - target)),
                }
            )
        except Exception as exc:
            send({"type": "error", "job_id": job_id, "error": f"{type(exc).__name__}: {exc}"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint-root", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--encoder-url", default="http://127.0.0.1:9550")
    args = parser.parse_args()
    protocol = sys.stdout

    def send(message):
        protocol.write(json.dumps(message, allow_nan=False) + "\n")
        protocol.flush()

    with contextlib.redirect_stdout(sys.stderr):
        serve(args, send)


if __name__ == "__main__":
    main()
