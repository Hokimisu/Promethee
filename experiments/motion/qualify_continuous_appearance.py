"""Measure per-chunk VRM preparation from a continuous ARDY trial.

The initial appearance must match an archived observation. Every subsequent
chunk starts from the last prepared appearance, as the future runtime must do.
This is offline qualification, not a live interactive session.
"""

import argparse
import copy
import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np

from promethee.appearance_checkpoint import appearance_checkpoint
from promethee.appearance_process import AppearancePreparation
from promethee.avatar_viewer import motion_document
from promethee.kinematic import read_contact_flags
from promethee.spatial import follow_attachment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--skeleton", type=Path, required=True)
    parser.add_argument("--avatar", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    provenance = json.loads((args.trial / "provenance.json").read_text(encoding="utf-8"))
    source_path = provenance["configuration"]["source"]
    if os.name == "nt" and source_path.startswith("/mnt/"):
        source_path = source_path[5].upper() + ":/" + source_path[7:]
    if hashlib.sha256(Path(source_path).read_bytes()).hexdigest() != provenance["source_sha256"]:
        raise ValueError("The source archive changed after the Core trial.")
    with np.load(source_path, allow_pickle=False) as source:
        end = provenance["configuration"]["source_end"]
        index = len(source["posed_joints"]) - 1 if end is None else end - 1
        initial_points = source["posed_joints"][index]
        initial_rotations = source["global_rot_mats"][index]
    observations = json.loads(args.observations.read_text(encoding="utf-8"))
    if isinstance(observations, dict):
        observations = observations["observations"]
    initial = next(
        (
            obs
            for obs in observations
            if obs.get("appearance") is not None
            and np.array_equal(np.asarray(obs["pose"]["positions"]), initial_points)
            and np.array_equal(np.asarray(obs["pose"]["rotations"]), initial_rotations)
        ),
        None,
    )
    if initial is None:
        raise ValueError("No matching observed Core pose and prepared appearance in the archive.")
    trial = json.loads((args.trial / "report.json").read_text(encoding="utf-8"))
    if trial["status"] != "passed_core_geometry_only":
        raise ValueError("The Core trial must pass before appearance qualification.")
    args.output.mkdir(parents=True, exist_ok=False)
    preparation = AppearancePreparation(
        avatar=args.avatar,
        script=Path(__file__).resolve().parents[2] / "web/avatar/measure-feet.mjs",
        output=args.output / "preparation",
    )
    report = {
        "status": "running",
        "chunks": [],
        "live_body_controlled": False,
        "visual_review": "pending",
        "trial_report_sha256": hashlib.sha256(
            (args.trial / "report.json").read_bytes()
        ).hexdigest(),
        "observations_sha256": hashlib.sha256(args.observations.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    previous = copy.deepcopy(initial)
    replay = []
    try:
        for chunk in trial["chunks"]:
            index = chunk["index"]
            path = args.trial / f"{index:02d}-processed.npz"
            document = motion_document(path, args.skeleton)
            document.update(
                initial_pose=previous["pose"], initial_appearance=previous["appearance"]
            )
            frames = []
            for body_pose in document["frames"]:
                observation = copy.deepcopy(previous)
                observation["pose"] = body_pose
                root = body_pose["positions"][0]
                observation["avatar"]["position"] = [root[0], root[2]]
                held = observation["avatar"]["holding"]
                if held:
                    observation["objects"][held] = follow_attachment(
                        observation["objects"][held], body_pose
                    )
                frames.append(observation)
            document["objects"] = [obs["objects"] for obs in frames]
            document["foot_contacts"] = read_contact_flags(path)
            started = time.perf_counter()
            job = preparation.submit(document, mode="--plant")
            item = None
            while item is None:
                item = preparation.poll()
                if item is None:
                    time.sleep(0.01)
            result = {
                "index": index,
                "job_id": job,
                "preparation_seconds": time.perf_counter() - started,
                "status": item["type"],
            }
            report["chunks"].append(result)
            if item["type"] != "prepared":
                raise ValueError(item.get("error", "Appearance preparation failed."))
            for i, observation in enumerate(frames):
                observation["appearance"] = appearance_checkpoint(
                    item["appearance"], i, observation["pose"]
                )
            replay.extend(frames)
            previous = copy.deepcopy(frames[-1])
            print(json.dumps(result), flush=True)
        np.savez(
            args.output / "motion.npz",
            posed_joints=np.array([obs["pose"]["positions"] for obs in replay]),
            global_rot_mats=np.array([obs["pose"]["rotations"] for obs in replay]),
            fps=np.asarray(20),
        )
        (args.output / "observations.json").write_text(
            json.dumps(replay, allow_nan=False), encoding="utf-8"
        )
        report["status"] = "passed_geometry_only"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        preparation.close()
        (args.output / "report.json").write_text(
            json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
