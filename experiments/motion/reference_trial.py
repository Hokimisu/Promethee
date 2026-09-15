"""Compare official explicit-feature feedback with reconstruction from raw poses.

Run with the isolated ARDY Python. This is an offline proposal experiment, not a
live controller or a qualification of physical support. No correction is applied.
The interactive demo retains normalized explicit features, not internal latents.
"""

import argparse
import hashlib
import inspect
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import torch
from ardy.constraints import Root2DConstraintSet
from ardy.model.load_model import load_model, load_text_encoder
from ardy.skeleton.definitions import CoreSkeleton27
from ardy.tools import seed_everything
from ardy.viz.core_skin import CoreSkin

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src/promethee"))
from ardy_continuation import encode_history, generation_window  # noqa: E402
from compare_postprocessing import measures  # noqa: E402

FIELDS = ("posed_joints", "global_rot_mats", "root_positions")


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
    parser.add_argument("--history-frames", type=int, default=4)
    parser.add_argument("--history-limit", type=int, default=4)
    parser.add_argument("--feedback", choices=("features", "raw-poses"), default="features")
    parser.add_argument(
        "--arrival-seconds", type=float, help="Sparse root path with a triangular speed profile."
    )
    parser.add_argument(
        "--settle-text", help="Text used after the planned arrival, preserving movement history."
    )
    args = parser.parse_args()
    if not 1 <= args.chunks <= 8 or not 0 <= args.seed < 2**31:
        parser.error("Use 1-8 horizons and an int31 seed.")
    if not 4 <= args.history_frames <= args.history_limit <= 160 or any(
        value % 4 for value in (args.history_frames, args.history_limit)
    ):
        parser.error("History must contain whole four-frame tokens, with at most 160 frames.")
    if not 1 <= len(args.text) <= 1000 or not np.isfinite(args.target).all():
        parser.error("Use bounded text and a finite target.")
    if max(abs(value) for value in args.target) > 5:
        parser.error("Target must remain inside the room.")
    if args.arrival_seconds is not None and not 2 <= args.arrival_seconds <= args.chunks * 2:
        parser.error("Arrival must be between two seconds and the end of this trial.")
    if args.settle_text is not None and (
        args.arrival_seconds is None
        or not 1 <= len(args.settle_text) <= 1000
        or not any(index * 2 >= args.arrival_seconds for index in range(args.chunks))
    ):
        parser.error("Settling text requires a post-arrival horizon and at most 1000 characters.")
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, args.output / "trial-source.py")
    config = {
        key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()
    }
    config["source_end"] = None
    provenance = {
        "kind": "qualification",
        "live_body_controlled": False,
        "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "configuration": config,
        "feedback": args.feedback,
        "postprocessing": False,
        "initial_history": "archived corrected poses, reconstructed once in both arms",
        "source_helpers_sha256": {
            name: hashlib.sha256(Path(inspect.getfile(function)).read_bytes()).hexdigest()
            for name, function in {
                "history": encode_history,
                "measures": measures,
                "model_loader": load_model,
            }.items()
        },
    }
    (args.output / "provenance.json").write_text(json.dumps(provenance, indent=2))
    with np.load(args.source, allow_pickle=False) as archive:
        if float(archive["fps"]) != 20 or len(archive["posed_joints"]) < args.history_frames:
            raise ValueError("Expected enough archived Core poses at 20 Hz.")
        history = {key: archive[key][-args.history_frames :].astype(np.float32) for key in FIELDS}
    model = load_model(
        "core", device="cuda", text_encoder=False, checkpoints_dir=args.checkpoint_root
    )
    model.text_encoder = load_text_encoder(mode="api", url=args.encoder_url, device="cuda")
    if model.gen_horizon_len != 40 or model.num_frames_per_token != 4:
        raise ValueError("This experiment requires Core Horizon40.")
    skin = CoreSkin(CoreSkeleton27())
    departure = history["root_positions"][-1, [0, 2]].copy()
    report = {"status": "running", "physical_support_qualified": False, "chunks": []}
    try:
        with torch.inference_mode():
            text_feat, text_mask = model._encode_text([args.text])
            settling = model._encode_text([args.settle_text]) if args.settle_text else None
            features, error = encode_history(model, history)
            report["initial_roundtrip_error_m"] = error
            for index in range(args.chunks):
                started = time.perf_counter()
                if args.feedback == "raw-poses" and index:
                    features, error = encode_history(model, history)
                length = len(history["posed_joints"])
                window, target_frame = generation_window(length, (args.chunks - index) * 40)
                constraints = []
                if target_frame is not None:
                    constraints.append(
                        Root2DConstraintSet(
                            model.skeleton,
                            torch.tensor([target_frame]),
                            torch.tensor([args.target], device="cuda"),
                        )
                    )
                if args.arrival_seconds is not None:
                    # Integrate acceleration then deceleration; sample goals every 0.5 s.
                    # The body motion remains entirely model-generated between goals.
                    offsets = np.arange(9, window - length, 10)
                    phase = np.clip((index * 40 + offsets + 1) / (20 * args.arrival_seconds), 0, 1)
                    fraction = np.where(phase <= 0.5, 2 * phase**2, 1 - 2 * (1 - phase) ** 2)
                    path = departure + fraction[:, None] * (np.asarray(args.target) - departure)
                    constraints = [
                        Root2DConstraintSet(
                            model.skeleton,
                            torch.tensor(length + offsets),
                            torch.tensor(path, dtype=torch.float32, device="cuda"),
                        )
                    ]
                observed, mask = model.motion_rep.create_conditions_from_constraints_batched(
                    constraints,
                    torch.tensor([window], device="cuda"),
                    to_normalize=True,
                    device="cuda",
                )
                seed_everything((args.seed + index) % 2**31)
                active_text, active_mask = (
                    settling
                    if settling and index * 2 >= args.arrival_seconds
                    else (text_feat, text_mask)
                )
                generated = model.autoregressive_step(
                    num_frames=window,
                    num_denoising_steps=10,
                    motion_mask=mask,
                    observed_motion=observed,
                    cfg_weight=(2.0, 2.0),
                    text_feat=active_text,
                    text_pad_mask=active_mask,
                    init_history_sequence=features,
                )
                decoded = model.motion_rep.inverse(generated, is_normalized=True)
                raw = {key: value[0, length:].cpu().numpy() for key, value in decoded.items()}
                if len(raw["posed_joints"]) != 40:
                    raise ValueError("Expected exactly one generated horizon.")
                np.savez(args.output / f"{index:02d}-raw.npz", **raw, fps=np.asarray(20))
                item = measures(raw, history["posed_joints"][-1], skin)
                item.update(index=index, history_frames=length, window_frames=window)
                item["text"] = (
                    args.settle_text
                    if settling and index * 2 >= args.arrival_seconds
                    else args.text
                )
                item["target_error_m"] = float(
                    np.linalg.norm(raw["root_positions"][-1, [0, 2]] - args.target)
                )
                item["total_seconds"] = time.perf_counter() - started
                report["chunks"].append(item)
                # Keep prior features, not the decoder's approximation of that history.
                features = torch.cat((features, generated[:, length:]), dim=1)[
                    :, -args.history_limit :
                ]
                history = {
                    key: np.concatenate((history[key], raw[key]))[-args.history_limit :]
                    for key in FIELDS
                }
                print(
                    json.dumps({key: value for key, value in item.items() if key != "skin"}),
                    flush=True,
                )
        report["status"] = "generated_reference_only"
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        (args.output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
