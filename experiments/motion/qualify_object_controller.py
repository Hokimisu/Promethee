"""Exercise the actual object controller from an archived Core pose, without model generation."""

import argparse
import copy
import hashlib
import json
import shutil
import time
from collections import deque
from pathlib import Path

import numpy as np

from promethee.avatar_viewer import motion_document
from promethee.execution import ExecutionService
from promethee.kinematic import KinematicController
from promethee.object_models import CONTACT_POINTS
from promethee.runtime import Runtime


class ArchivedPoseWorker:
    """No generated-result substitute: only the existing skeleton is supplied."""

    pending = None

    def __init__(self, output, skeleton):
        self.output = output
        self.messages = deque([{"type": "ready", "skeleton": skeleton}])

    def poll(self):
        return self.messages.popleft() if self.messages else None

    def submit(self, job):
        raise RuntimeError("This qualification must not generate a substitute motor trajectory.")

    def close(self):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--motion", type=Path, required=True)
    parser.add_argument("--skeleton", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--heading-degrees", type=float, default=0)
    parser.add_argument("--offset-xz", type=float, nargs=2, default=[0, 0])
    parser.add_argument("--object-position", type=float, nargs=3, default=[0, 1.15, 0.25])
    parser.add_argument("--asset", choices=sorted(CONTACT_POINTS), default="plush")
    args = parser.parse_args()
    if not np.isfinite([args.heading_degrees, *args.offset_xz, *args.object_position]).all():
        parser.error("Trial coordinates must be finite.")
    args.output.mkdir(parents=True, exist_ok=False)
    source_root = Path(__file__).resolve().parents[2]
    sources = [Path(__file__)] + [
        source_root / "src" / "promethee" / name
        for name in ("object_actions.py", "object_models.py", "arm_reach.py", "kinematic.py")
    ]
    source_hashes = {}
    for source in sources:
        shutil.copy2(source, args.output / source.name)
        source_hashes[source.name] = hashlib.sha256(source.read_bytes()).hexdigest()
    (args.output / "config.json").write_text(
        json.dumps(
            {
                key: str(value) if isinstance(value, Path) else value
                for key, value in vars(args).items()
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    motion = motion_document(args.motion, args.skeleton)
    pose = motion["frames"][0]
    angle = np.deg2rad(args.heading_degrees)
    rotation = np.array(
        [[np.cos(angle), 0, np.sin(angle)], [0, 1, 0], [-np.sin(angle), 0, np.cos(angle)]]
    )
    offset = np.array([args.offset_xz[0], 0, args.offset_xz[1]])

    def point(value):
        return (rotation @ value + offset).tolist()

    pose["positions"] = [point(value) for value in pose["positions"]]
    pose["rotations"] = (rotation @ np.asarray(pose["rotations"])).tolist()
    path = args.output / "world.sqlite3"
    service = ExecutionService(Runtime(path, data_origin="session", session_kind="qualification"))
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
        service, ArchivedPoseWorker(args.output, motion["skeleton"]), object_interactions=True
    )
    controller.tick()
    observations, results = [], []

    def perform(rid, kind, values, expected, cancel_after=None):
        started = time.monotonic()
        service.submit(rid, service.get_world()["revision"], {"kind": kind, "args": values})
        controller.tick()
        play_start = time.monotonic()
        while service.get(rid)["status"] in {"accepted", "running"}:
            if time.monotonic() - started > 20:
                raise TimeoutError("Object action exceeded its qualification deadline.")
            if cancel_after is not None and time.monotonic() - play_start >= cancel_after:
                service.cancel(rid)
            time.sleep(0.05)
            controller.tick()
            observations.append(copy.deepcopy(controller.observation))
        item = service.get(rid)
        result = {
            "request_id": rid,
            "status": item["status"],
            "elapsed_seconds": time.monotonic() - started,
            "holding": service.get_world()["avatar"]["holding"],
            "error": item.get("error"),
        }
        results.append(result)
        print(json.dumps(result), flush=True)
        assert item["status"] == expected, result

    try:
        perform(
            "spawn",
            "spawn",
            {"object_id": "sample", "asset": args.asset, "position": point(args.object_position)},
            "completed",
        )
        perform("take", "take", {"object_id": "sample"}, "completed")
        perform("occupied", "take", {"object_id": "sample"}, "rejected")
        placement = np.asarray(args.object_position) + [0, -0.02, 0.02]
        perform("place", "place", {"position": point(placement)}, "completed")
        perform("cancel-before-contact", "take", {"object_id": "sample"}, "cancelled", 1.0)
        assert controller.observation["avatar"]["holding"] is None
        perform("cancel-after-contact", "take", {"object_id": "sample"}, "cancelled", 3.5)
        assert controller.observation["avatar"]["holding"] == "sample"
        before = copy.deepcopy(controller.observation)
        controller.close()
        service = ExecutionService(Runtime(path))
        controller = KinematicController(
            service, ArchivedPoseWorker(args.output, motion["skeleton"]), object_interactions=True
        )
        controller.tick()
        assert controller.observation == before
        replacement = np.asarray(args.object_position) + [0, 0, 0.01]
        perform("place-after-restart", "place", {"position": point(replacement)}, "completed")
        perform(
            "floor-intersection",
            "spawn",
            {"object_id": "bad", "asset": args.asset, "position": [1, 0, 1]},
            "failed",
        )
        perform("missing", "take", {"object_id": "absent"}, "rejected")
    finally:
        controller.close()
        (args.output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    np.savez_compressed(
        args.output / "motion.npz",
        fps=20.0,
        posed_joints=np.array([o["pose"]["positions"] for o in observations]),
        global_rot_mats=np.array([o["pose"]["rotations"] for o in observations]),
    )
    (args.output / "objects.json").write_text(json.dumps(observations), encoding="utf-8")
    report = {
        "purpose": "developer production-controller qualification, not personal memory",
        "source_motion_sha256": hashlib.sha256(args.motion.read_bytes()).hexdigest(),
        "source_skeleton_sha256": hashlib.sha256(args.skeleton.read_bytes()).hexdigest(),
        "source_code_sha256": source_hashes,
        "heading_degrees": args.heading_degrees,
        "offset_xz": args.offset_xz,
        "object_position_before_world_transform": args.object_position,
        "asset": args.asset,
        "object_spawn_orientation": "world identity, not rotated with the trial",
        "samples": len(observations),
        "sample_period_seconds": 0.05,
        "preparation_delays_omitted_from_replay": True,
        "gravity_or_finger_grasp_validated": False,
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
