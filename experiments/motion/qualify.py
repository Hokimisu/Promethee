"""Real-model T02 measurements. Run in the isolated ARDY environment, never CI."""

import argparse
import json
import shutil
import time
from pathlib import Path

import numpy as np
import torch
from ardy.constraints import Root2DConstraintSet
from ardy.model.load_model import load_model, load_text_encoder
from ardy.motion_rep.tools import length_to_mask
from ardy.postprocess import post_process_motion
from ardy.tools import seed_everything

CASES = {
    "calibration": [
        (101, "A person walks forward.", [0, 0], [0, 1.5], 0.0),
        (102, "A person walks slowly to the left.", [0, 0], [1.2, 0], 0.0),
        (103, "A person is standing and waving with the right hand.", [0, 0], [0, 0], 0.0),
    ],
    "verification": [
        (201, "A person walks diagonally.", [-1, 0.5], [0.2, 1.8], 0.4),
        (202, "A person walks backwards.", [0.5, 1], [0.5, -0.5], 0.0),
        (203, "A person is standing and raises both arms.", [-0.5, -0.5], [-0.5, -0.5], 1.0),
    ],
    "holdout": [
        (301, "A person walks diagonally backwards.", [1, -1], [-0.5, -2], -0.3),
        (302, "A person walks forward at a relaxed pace.", [-1.5, -1], [0, -1], 1.57),
        (303, "A person is standing and waves with the left hand.", [-2, 1], [-2, 1], -1.0),
    ],
}


def sync_time():
    torch.cuda.synchronize()
    return time.perf_counter()


def arrays(output):
    return {key: value.detach().cpu().numpy() for key, value in output.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=list(CASES), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--encoder-url", default="http://127.0.0.1:9550")
    parser.add_argument("--frames", type=int, choices=[40, 120], default=120)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, args.output / "qualify-source.py")
    start = sync_time()
    model = load_model(
        "core", device="cuda", text_encoder=False, checkpoints_dir=str(args.checkpoint_root)
    )
    load_seconds = sync_time() - start
    model.text_encoder = load_text_encoder(mode="api", url=args.encoder_url, device="cuda")
    skeleton = model.skeleton
    conventions = {
        "skeleton": skeleton.name,
        "joint_names": skeleton.bone_order_names,
        "parents": skeleton.joint_parents.tolist(),
        "neutral_joints": skeleton.neutral_joints.tolist(),
        "feet": skeleton.foot_joint_names,
        "fps": model.motion_rep.fps,
        "torch": torch.__version__,
        "gpu": torch.cuda.get_device_name(),
        "model_load_seconds": load_seconds,
    }
    (args.output / "conventions.json").write_text(json.dumps(conventions, indent=2))
    records = []
    for seed, prompt, origin, target, heading in CASES[args.phase]:
        seed_everything(seed)
        start = sync_time()
        text_feat, text_mask = model._encode_text([prompt])
        encode_seconds = sync_time() - start
        lengths = torch.tensor([args.frames], device="cuda")
        constraints = [
            Root2DConstraintSet(
                skeleton,
                torch.tensor([0, args.frames - 1], device="cuda"),
                torch.tensor(
                    [[0, 0], [target[0] - origin[0], target[1] - origin[1]]],
                    device="cuda",
                    dtype=torch.float32,
                ),
            )
        ]
        observed, mask = model.motion_rep.create_conditions_from_constraints_batched(
            constraints,
            lengths,
            to_normalize=True,
            device="cuda",
        )
        window_seconds = []
        original_window = model._generate_window

        def measured_window(
            *positional, _method=original_window, _timings=window_seconds, **kwargs
        ):
            began = sync_time()
            result = _method(*positional, **kwargs)
            _timings.append(sync_time() - began)
            return result

        model._generate_window = measured_window
        torch.cuda.reset_peak_memory_stats()
        start = sync_time()
        with torch.inference_mode():
            motion = model(
                [prompt],
                args.frames,
                10,
                length_to_mask(lengths),
                torch.tensor([heading], device="cuda"),
                mask,
                observed,
                cfg_weight=(2.0, 2.0),
                text_feat=text_feat,
                text_pad_mask=text_mask,
                crop_history_length=160,
                progress_bar=lambda indices: indices,
            )
            output = model.motion_rep.inverse(motion, is_normalized=True)
        generation_seconds = sync_time() - start
        model._generate_window = original_window
        raw = arrays(output)
        start = sync_time()
        corrected = post_process_motion(
            output["local_rot_mats"],
            output["root_positions"],
            output["foot_contacts"],
            skeleton,
            constraint_lst=constraints,
        )
        output.update(corrected)
        postprocess_seconds = sync_time() - start
        processed = arrays(output)
        # Translate the entire observed trajectory from ARDY's local origin.
        # Do not snap the last pose to the requested target.
        offset = np.asarray([origin[0], 0, origin[1]], dtype=np.float32)
        for data in (raw, processed):
            for field in ("root_positions", "posed_joints"):
                data[field] = data[field] + offset
        finite = all(np.isfinite(value).all() for value in processed.values())
        if not finite:
            raise RuntimeError(f"Non-finite motion: seed {seed}")
        root = processed["root_positions"][0]
        raw_root = raw["root_positions"][0]
        record = {
            "seed": seed,
            "prompt": prompt,
            "origin_xz": origin,
            "target_xz": target,
            "heading_radians": heading,
            "frames": args.frames,
            "fps": 20,
            "encode_seconds": encode_seconds,
            "generation_seconds": generation_seconds,
            "window_seconds": window_seconds,
            "postprocess_seconds": postprocess_seconds,
            "raw_start_error_m": float(np.linalg.norm(raw_root[0, [0, 2]] - origin)),
            "raw_target_error_m": float(np.linalg.norm(raw_root[-1, [0, 2]] - target)),
            "target_error_m": float(np.linalg.norm(root[-1, [0, 2]] - target)),
            "root_max_frame_step_m": float(np.linalg.norm(np.diff(root, axis=0), axis=-1).max()),
            "gpu_peak_allocated_bytes": torch.cuda.max_memory_allocated(),
            "gpu_peak_reserved_bytes": torch.cuda.max_memory_reserved(),
            "all_finite": bool(finite),
        }
        if args.frames == 40:
            record["first_pose_seconds"] = generation_seconds
            record["first_pose_with_text_seconds"] = encode_seconds + generation_seconds
        for label, data in (("raw", raw), ("processed", processed)):
            np.savez(
                args.output / f"{seed}-{label}.npz",
                **{key: value[0] for key, value in data.items()},
                fps=np.asarray(20),
                text=np.asarray(prompt),
            )
        records.append(record)
        (args.output / "measurements.json").write_text(json.dumps(records, indent=2))
        print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
