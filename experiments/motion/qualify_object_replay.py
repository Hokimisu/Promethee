"""Prepare an already-attached object replay; does not claim approach or grasp."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from promethee.avatar_viewer import motion_document
from promethee.spatial import HANDS, follow_attachment
from promethee.world import validate_observation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--motion", type=Path, required=True)
    parser.add_argument("--skeleton", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--side", choices=["right", "left"], default="right")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, args.output / "qualification-source.py")
    motion = motion_document(args.motion, args.skeleton)
    joint = "RightHand" if args.side == "right" else "LeftHand"
    initial_rotation = motion["frames"][0]["rotations"][HANDS[joint]]
    attachment = {
        "joint": joint,
        "position": [-0.07 if args.side == "right" else 0.07, 0, 0],
        "rotation": [list(row) for row in zip(*initial_rotation, strict=True)],
    }
    obj = {"asset": "plush", "spatial": {"attachment": attachment}}
    observations = []
    for pose in motion["frames"]:
        objects = {"sample": follow_attachment(obj, pose)}
        observation = {
            "pose": pose,
            "objects": objects,
            "avatar": {
                "position": [pose["positions"][0][0], pose["positions"][0][2]],
                "holding": "sample",
                "seated_on": None,
            },
        }
        observations.append(validate_observation(observation))
    path = args.output / "objects.json"
    path.write_text(json.dumps(observations, allow_nan=False), encoding="utf-8")
    # Validate the same loader that the browser server uses, including frame identity.
    loaded = motion_document(args.motion, args.skeleton, path)
    report = {
        "purpose": "developer attached-object replay, not personal memory",
        "grasp_validated": False,
        "frames": len(loaded["objects"]),
        "hand": joint,
        "source_motion_sha256": hashlib.sha256(args.motion.read_bytes()).hexdigest(),
        "observations_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
