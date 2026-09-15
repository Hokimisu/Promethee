"""Qualify ARDY continuation from corrected Core motion before runtime integration.

Run with the isolated ARDY Python. This experiment does not command a live body:
its seed history is an archived trajectory and its future chunks are proposals.
It never counts the autoencoder's reconstructed history as newly executed motion.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from ardy.constraints import FullBodyConstraintSet, Root2DConstraintSet
from ardy.model.load_model import load_model, load_text_encoder
from ardy.skeleton.definitions import CoreSkeleton27
from ardy.tools import seed_everything
from ardy.viz.core_skin import CoreSkin

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src/promethee"))
from ardy_contacts import (  # noqa: E402
    measure_skin_contacts,
    project_support,
    stabilize_contacts,
    validate_sole_contacts,
)
from ardy_geometry import continue_from_pose  # noqa: E402

FIELDS = ("posed_joints", "global_rot_mats", "root_positions")


def encode_history(model, values):
    """Rebuild model features from corrected world rotations, not stale latents."""
    matrices = torch.as_tensor(values["global_rot_mats"], device="cuda").unsqueeze(0)
    root = torch.as_tensor(values["root_positions"], device="cuda").unsqueeze(0)
    local = matrices.clone()
    for joint, parent in enumerate(model.skeleton.joint_parents.tolist()):
        if parent >= 0:
            local[:, :, joint] = matrices[:, :, parent].transpose(-1, -2) @ matrices[:, :, joint]
    encoded = model.motion_rep(local_joint_rots=local, root_positions=root, to_normalize=True)
    restored = model.motion_rep.inverse(encoded, is_normalized=True)
    expected = torch.as_tensor(values["posed_joints"], device="cuda")
    error = torch.linalg.vector_norm(restored["posed_joints"][0] - expected, dim=-1).max().item()
    if not torch.isfinite(encoded).all() or error > 0.002:
        raise ValueError(f"History reconstruction changes corrected joints by {error:.6f} m.")
    return encoded, error


def pose(values, index=-1):
    return {
        "skeleton": "cskel27",
        "positions": values["posed_joints"][index].tolist(),
        "rotations": values["global_rot_mats"][index].tolist(),
    }


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--checkpoint-root", required=True)
    parser.add_argument("--encoder-url", default="http://127.0.0.1:9550")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--target", type=float, nargs=2, required=True)
    parser.add_argument("--chunks", type=int, default=3)
    parser.add_argument("--history-frames", type=int, default=40)
    parser.add_argument("--source-end", type=int, help="Exclusive end of the archived history.")
    parser.add_argument(
        "--arrival-pose",
        action="store_true",
        help="Constrain arrival to the translated source pose; requires a suitable source stance.",
    )
    args = parser.parse_args()
    if not 1 <= args.chunks <= 8 or not 4 <= args.history_frames <= 160:
        parser.error("Use 1-8 chunks and 4-160 history frames.")
    if args.history_frames % 4 or not 0 <= args.seed < 2**31:
        parser.error("History must contain whole four-frame tokens; seed must fit int31.")
    if not 1 <= len(args.text) <= 1000 or not np.isfinite(args.target).all():
        parser.error("Provide a bounded motion text and finite target.")
    if max(abs(value) for value in args.target) > 5:
        parser.error("Target must remain inside the room.")
    args.output.mkdir(parents=True, exist_ok=False)
    configuration = {
        key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()
    }
    dump(
        args.output / "provenance.json",
        {
            "kind": "qualification",
            "live_body_controlled": False,
            "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "configuration": configuration,
        },
    )
    with np.load(args.source, allow_pickle=False) as source:
        count = len(source["posed_joints"])
        end = count if args.source_end is None else args.source_end
        if not args.history_frames <= end <= count or float(source["fps"]) != 20:
            raise ValueError("History range must exist in a 20 Hz recording.")
        history = {
            key: source[key][end - args.history_frames : end].astype(np.float32) for key in FIELDS
        }
    if history["posed_joints"].shape != (args.history_frames, 27, 3):
        raise ValueError("Expected Core27 positions.")
    if history["global_rot_mats"].shape != (args.history_frames, 27, 3, 3):
        raise ValueError("Expected Core27 rotations.")
    if history["root_positions"].shape != (args.history_frames, 3):
        raise ValueError("Expected one root position per frame.")
    if any(not np.isfinite(value).all() for value in history.values()):
        raise ValueError("History must contain finite values.")
    arrival = pose(history)
    arrival_points = np.asarray(arrival["positions"], dtype=np.float32)
    arrival_points[:, [0, 2]] += np.asarray(args.target) - arrival_points[0, [0, 2]]
    report = {
        "status": "running",
        "chunks": [],
        "runtime_integrated": False,
        "visual_review": "pending",
    }
    try:
        started = time.perf_counter()
        model = load_model(
            "core", device="cuda", text_encoder=False, checkpoints_dir=args.checkpoint_root
        )
        model.text_encoder = load_text_encoder(mode="api", url=args.encoder_url, device="cuda")
        skin = CoreSkin(CoreSkeleton27())
        horizon = model.gen_horizon_len
        if horizon != 40 or model.num_frames_per_token != 4:
            raise ValueError("This trial is pinned to Core Horizon40 with four-frame tokens.")
        report["model_load_seconds"] = time.perf_counter() - started
        with torch.inference_mode():
            started = time.perf_counter()
            text_feat, text_pad_mask = model._encode_text([args.text])
            torch.cuda.synchronize()
            report["text_encode_seconds"] = time.perf_counter() - started
            for index in range(args.chunks):
                item = {"index": index, "accepted": False}
                report["chunks"].append(item)
                started = time.perf_counter()
                encoded, item["history_roundtrip_error_m"] = encode_history(model, history)
                history_length = len(history["posed_joints"])
                remaining = (args.chunks - index) * horizon
                window = history_length + remaining
                constraints = [
                    Root2DConstraintSet(
                        model.skeleton,
                        torch.tensor([window - 1]),
                        torch.tensor([args.target], device="cuda"),
                    )
                ]
                if args.arrival_pose:
                    constraints.append(
                        FullBodyConstraintSet(
                            model.skeleton,
                            torch.tensor([window - 1]),
                            torch.tensor(arrival_points, device="cuda").unsqueeze(0),
                            torch.tensor(arrival["rotations"], device="cuda").unsqueeze(0),
                        )
                    )
                observed, mask = model.motion_rep.create_conditions_from_constraints_batched(
                    constraints,
                    torch.tensor([window], device="cuda"),
                    to_normalize=True,
                    device="cuda",
                )
                seed_everything((args.seed + index) % 2**31)
                torch.cuda.synchronize()
                item["history_prepare_seconds"] = time.perf_counter() - started
                generated_at = time.perf_counter()
                generated = model.autoregressive_step(
                    num_frames=window,
                    num_denoising_steps=10,
                    motion_mask=mask,
                    observed_motion=observed,
                    cfg_weight=(2.0, 2.0),
                    text_feat=text_feat,
                    text_pad_mask=text_pad_mask,
                    init_history_sequence=encoded,
                )
                torch.cuda.synchronize()
                item["generation_seconds"] = time.perf_counter() - generated_at
                decoded = model.motion_rep.inverse(generated, is_normalized=True)
                raw = {
                    key: value[0, history_length:].cpu().numpy() for key, value in decoded.items()
                }
                if len(raw["posed_joints"]) != horizon:
                    raise ValueError("A single autoregressive step must emit exactly one horizon.")
                np.savez(args.output / f"{index:02d}-raw.npz", **raw, fps=np.asarray(20))
                item["raw_boundary_step_m"] = float(
                    np.linalg.norm(
                        raw["posed_joints"][0] - history["posed_joints"][-1], axis=-1
                    ).max()
                )
                values = {key: value.copy() for key, value in raw.items()}
                continue_from_pose(values, pose(history), skin.skeleton)
                item["contact_residual_m"] = stabilize_contacts(values, skin.skeleton)
                item["support_projection"] = project_support(values, skin)
                contacts = measure_skin_contacts(values, skin)
                item["contacts"] = contacts
                np.savez(args.output / f"{index:02d}-processed.npz", **values, fps=np.asarray(20))
                validate_sole_contacts(contacts, continuous_support=True)
                item["corrected_boundary_step_m"] = float(
                    np.linalg.norm(
                        values["posed_joints"][0] - history["posed_joints"][-1], axis=-1
                    ).max()
                )
                if item["corrected_boundary_step_m"] > 0.02:
                    raise ValueError("Corrected chunk exceeds the existing 2 cm continuity limit.")
                step = np.linalg.norm(np.diff(values["posed_joints"], axis=0), axis=-1).max()
                item["max_joint_step_m"] = float(step)
                if step > 0.3:
                    raise ValueError("Chunk exceeds the existing 30 cm joint-step limit.")
                item["target_error_m"] = float(
                    np.linalg.norm(values["root_positions"][-1, [0, 2]] - args.target)
                )
                if index == args.chunks - 1 and item["target_error_m"] > 0.05:
                    raise ValueError("Final chunk misses the target by more than 5 cm.")
                item["accepted"] = True
                item["total_seconds"] = time.perf_counter() - started
                # Keep the original corrected history. Discard its re-decoded approximation.
                history = {
                    key: np.concatenate((history[key], values[key]))[-160:] for key in FIELDS
                }
                print(
                    json.dumps(
                        {
                            key: value
                            for key, value in item.items()
                            if key not in {"contacts", "support_projection"}
                        }
                    ),
                    flush=True,
                )
                dump(args.output / "report.json", report)
        report["status"] = "passed_core_geometry_only"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        dump(args.output / "report.json", report)


if __name__ == "__main__":
    main()
