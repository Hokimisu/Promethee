"""Compare raw, official-demo and Promethee processing on identical saved proposals.

Run in the isolated ARDY environment. No model inference or live world mutation.
Official-demo means its optional postprocessing enabled: the demo only calls it
when a constraint falls inside the emitted horizon. Raw is its default setting.
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
from ardy.constraints import FullBodyConstraintSet, Root2DConstraintSet
from ardy.postprocess import post_process_motion
from ardy.skeleton.definitions import CoreSkeleton27
from ardy.viz.core_skin import CoreSkin

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src/promethee"))
from ardy_contacts import measure_skin_contacts  # noqa: E402

FIELDS = ("posed_joints", "global_rot_mats", "local_rot_mats", "root_positions", "foot_contacts")


def measures(values, previous, skin):
    points = values["posed_joints"]
    speed = np.linalg.norm(np.diff(points[:, 0][:, [0, 2]], axis=0), axis=-1) * 20
    return {
        "root_speed_max_m_s": float(speed.max()),
        "root_speed_p95_m_s": float(np.quantile(speed, 0.95)),
        "boundary_joint_step_m": float(np.linalg.norm(points[0] - previous, axis=-1).max()),
        "max_joint_step_m": float(np.linalg.norm(np.diff(points, axis=0), axis=-1).max()),
        "final_ankle_distance_m": float(np.linalg.norm(points[-1, 21] - points[-1, 25])),
        "missing_predicted_support_frames": np.flatnonzero(
            ~values["foot_contacts"].any(-1)
        ).tolist(),
        "skin": measure_skin_contacts(values, skin),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    provenance = json.loads((args.trial / "provenance.json").read_text())
    config = provenance["configuration"]
    if config.get("arrival_seconds") is not None:
        raise ValueError(
            "Sparse arrival trials require their exact constraint replay; unsupported here."
        )
    source = Path(config["source"])
    if hashlib.sha256(source.read_bytes()).hexdigest() != provenance["source_sha256"]:
        raise ValueError("The source archive changed.")
    with np.load(source, allow_pickle=False) as archive:
        index = config["source_end"] - 1 if config["source_end"] is not None else -1
        initial = archive["posed_joints"][index].copy()
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, args.output / "comparison-source.py")
    skeleton = CoreSkeleton27()
    skin = CoreSkin(skeleton)
    report = {
        "kind": "qualification",
        "live_world_controlled": False,
        "same_proposals": True,
        "independent_generation_feedback": False,
        "comparison_scope": (
            "Processing ablation only: all variants use the same saved proposals, "
            "conditioned by the source trial's history. Joined variants do not rerun "
            "the model with their own corrected history."
        ),
        "official_postprocessing_enabled": True,
        "official_wrapper_sha256": hashlib.sha256(
            Path(inspect.getfile(post_process_motion)).read_bytes()
        ).hexdigest(),
        "official_contact_threshold": 0.5,
        "official_root_margin_m": 0.04,
        "contact_flags": (
            "Original model predictions retained for all variants; skin measured separately."
        ),
        "trial_provenance": provenance,
        "chunks": [],
    }
    joined = {method: [] for method in ("raw", "official", "promethee")}
    indices = {method: [] for method in joined}
    previous = {method: initial for method in joined}
    paths = sorted(args.trial.glob("[0-9][0-9]-raw.npz"))
    if not paths or len(paths) > config["chunks"]:
        raise ValueError("The proposal count is empty or exceeds the requested trial.")
    if [int(path.name.split("-")[0]) for path in paths] != list(range(len(paths))):
        raise ValueError("The raw proposal series has a missing or reordered block.")
    report["requested_chunks"] = config["chunks"]
    report["generated_chunks"] = len(paths)
    report["source_trial_partial"] = len(paths) != config["chunks"]
    for path in paths:
        index = int(path.name.split("-")[0])
        with np.load(path, allow_pickle=False) as archive:
            raw = {key: archive[key].copy() for key in FIELDS}
        length = len(raw["posed_joints"])
        constraints = []
        if config.get("root_path"):
            phase = (index * length + np.arange(1, length + 1)) / (config["chunks"] * length)
            blend = 10 * phase**3 - 15 * phase**4 + 6 * phase**5
            departure = initial[0, [0, 2]]
            positions = departure + blend[:, None] * (np.asarray(config["target"]) - departure)
            constraints.append(
                Root2DConstraintSet(skeleton, torch.arange(length), torch.tensor(positions))
            )
        elif index == config["chunks"] - 1:
            constraints.append(
                Root2DConstraintSet(
                    skeleton, torch.tensor([length - 1]), torch.tensor([config["target"]])
                )
            )
        if index == config["chunks"] - 1 and (
            config.get("arrival_pose") or config.get("arrival_stance")
        ):
            arrival = json.loads((args.trial / "arrival-constraint.json").read_text())
            constraints.append(
                FullBodyConstraintSet(
                    skeleton,
                    torch.tensor([length - 1]),
                    torch.tensor([arrival["positions"]]),
                    torch.tensor([arrival["rotations"]]),
                )
            )
        item = {
            "index": index,
            "raw_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "official_filter_called": bool(constraints),
        }
        started = time.perf_counter()
        if constraints:
            with torch.inference_mode():
                corrected = post_process_motion(
                    torch.from_numpy(raw["local_rot_mats"][None]),
                    torch.from_numpy(raw["root_positions"][None]),
                    torch.from_numpy(raw["foot_contacts"][None]).float(),
                    skeleton,
                    constraint_lst=constraints,
                )
            official = {key: value[0].cpu().numpy() for key, value in corrected.items()}
            official["foot_contacts"] = raw["foot_contacts"].copy()
        else:
            official = raw
        item["official_seconds"] = time.perf_counter() - started
        variants = {"raw": raw, "official": official}
        processed = path.with_name(path.name.replace("raw", "processed"))
        if processed.exists():
            with np.load(processed, allow_pickle=False) as archive:
                variants["promethee"] = {key: archive[key].copy() for key in FIELDS}
        for method, values in variants.items():
            item[method] = measures(values, previous[method], skin)
            item[method]["max_change_from_raw_m"] = float(
                np.linalg.norm(values["posed_joints"] - raw["posed_joints"], axis=-1).max()
            )
            previous[method] = values["posed_joints"][-1]
            joined[method].append(values)
            indices[method].append(index)
            np.savez(args.output / f"{index:02d}-{method}.npz", **values, fps=np.asarray(20))
        report["chunks"].append(item)
    report["series"] = {}
    for method, chunks in joined.items():
        contiguous = indices[method] == list(range(len(chunks)))
        report["series"][method] = {
            "chunk_indices": indices[method],
            "frames": sum(len(chunk["posed_joints"]) for chunk in chunks),
            "complete": len(chunks) == config["chunks"] and contiguous,
            "contiguous_prefix": contiguous,
        }
        if chunks and contiguous:
            values = {key: np.concatenate([chunk[key] for chunk in chunks]) for key in FIELDS}
            np.savez(args.output / f"joined-{method}.npz", **values, fps=np.asarray(20))
    (args.output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    for item in report["chunks"]:
        print(json.dumps(item), flush=True)


if __name__ == "__main__":
    main()
