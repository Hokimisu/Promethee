"""Verify the pinned VRM profile and an actual controller refusal before playback."""

import argparse
import copy
import hashlib
import json
import shutil
import struct
from pathlib import Path

import numpy as np
from qualify_object_controller import ArchivedPoseWorker

from promethee.avatar_reach import PIXIV_SHA256, PixivArmReach
from promethee.avatar_viewer import motion_document
from promethee.execution import ExecutionService
from promethee.kinematic import KinematicController
from promethee.object_actions import prepare_object_action
from promethee.runtime import Runtime
from promethee.world import validate_observation


def rest_positions(path):
    blob = path.read_bytes()
    if hashlib.sha256(blob).hexdigest() != PIXIV_SHA256:
        raise ValueError("Use the pinned pixiv model.")
    length = struct.unpack_from("<I", blob, 12)[0]
    gltf = json.loads(blob[20 : 20 + length])
    matrices = {}

    def visit(index, parent):
        node = gltf["nodes"][index]
        if "matrix" in node:
            local = np.array(node["matrix"]).reshape(4, 4).T
        else:
            q = np.array(node.get("rotation", [0, 0, 0, 1]), dtype=float)
            q /= np.linalg.norm(q)
            x, y, z, w = q
            rotation = np.array(
                [
                    [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                    [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                    [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
                ]
            )
            local = np.eye(4)
            local[:3, :3] = rotation @ np.diag(node.get("scale", [1, 1, 1]))
            local[:3, 3] = node.get("translation", [0, 0, 0])
        matrices[index] = parent @ local
        for child in node.get("children", []):
            visit(child, matrices[index])

    for index in gltf["scenes"][gltf.get("scene", 0)]["nodes"]:
        visit(index, np.eye(4))
    return {
        name: matrices[bone["node"]][:3, 3]
        for name, bone in gltf["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"].items()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("avatar", "skeleton", "source-motion", "unreachable-motion", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--replays", type=Path, nargs="*", default=[])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "config.json").write_text(
        json.dumps(
            {
                key: [str(p) for p in value] if isinstance(value, list) else str(value)
                for key, value in vars(args).items()
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    sources = [Path(__file__), Path(__file__).with_name("qualify_object_controller.py")]
    sources += [
        root / "src" / "promethee" / name
        for name in (
            "avatar_reach.py",
            "pixiv_arm_profile.json",
            "object_actions.py",
            "kinematic.py",
        )
    ]
    hashes = {}
    for source in sources:
        shutil.copy2(source, args.output / source.name)
        hashes[source.name] = hashlib.sha256(source.read_bytes()).hexdigest()
    report = {
        "purpose": "developer qualification, excluded from personal memory",
        "sources": hashes,
    }
    reach = PixivArmReach()
    try:
        actual = rest_positions(args.avatar)
        error = max(
            float(np.linalg.norm(actual[name] - bone["rest_position"]))
            for name, bone in reach.profile["bones"].items()
        )
        report["maximum_rest_position_error_m"] = error
        assert error < 1e-6
        data = motion_document(args.source_motion, args.skeleton)
        skeleton, pose = data["skeleton"], data["frames"][0]
        high = motion_document(args.unreachable_motion, args.skeleton)
        rejected = []
        for index, frame in enumerate(high["frames"]):
            try:
                reach.check(frame, skeleton, "RightHand")
            except ValueError as exc:
                rejected.append({"frame": index, "error": str(exc)})
        report["known_unreachable_motion"] = {
            "sha256": hashlib.sha256(args.unreachable_motion.read_bytes()).hexdigest(),
            "rejected": rejected,
        }
        assert rejected, "The known unreachable wrist was accepted."
        report["replays"] = []
        for path in args.replays:
            observations = json.loads(path.read_text(encoding="utf-8"))
            hands = {
                obj["spatial"]["attachment"]["joint"]
                for obs in observations
                for obj in obs["objects"].values()
                if obj["spatial"]["attachment"]
            }
            for observation in observations:
                validate_observation(observation)
                for hand in hands:
                    reach.check(observation["pose"], skeleton, hand)
            report["replays"].append(
                {
                    "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "poses": len(observations),
                    "hands": sorted(hands),
                    "status": "passed",
                }
            )
        service = ExecutionService(
            Runtime(
                args.output / "world.sqlite3", data_origin="session", session_kind="qualification"
            )
        )
        handle = service.acquire_controller(source="kinematic", supported_actions=["move"])
        handle.reconcile(
            {
                "pose": pose,
                "objects": {},
                "avatar": {
                    "position": [pose["positions"][0][0], pose["positions"][0][2]],
                    "holding": None,
                    "seated_on": None,
                },
            },
            stopped=True,
        )
        handle.release()
        controller = KinematicController(
            service,
            ArchivedPoseWorker(args.output, skeleton),
            object_interactions=True,
            arm_reach_check=reach.check,
        )
        try:
            controller.tick()
            service.submit(
                "spawn",
                service.get_world()["revision"],
                {
                    "kind": "spawn",
                    "args": {"asset": "plush", "object_id": "limit", "position": [0, 1.45, 0.45]},
                },
            )
            controller.tick()
            controller.tick()
            assert service.get("spawn")["status"] == "completed"
            before = copy.deepcopy(controller.observation)
            action = {"kind": "take", "args": {"object_id": "limit"}}
            baseline = prepare_object_action(before, skeleton, action)
            report["core_only_preflight_frames"] = len(baseline)
            service.submit("take", service.get_world()["revision"], action)
            controller.tick()
            result = service.get("take")
            report["controller_refusal"] = {
                "status": result["status"],
                "error": result.get("error"),
                "observation_unchanged": controller.observation == before,
                "trajectory_started": controller.trajectory is not None,
            }
            assert result["status"] == "failed"
            assert controller.observation == before and controller.trajectory is None
        finally:
            controller.close()
        report["status"] = "passed"
    finally:
        (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
