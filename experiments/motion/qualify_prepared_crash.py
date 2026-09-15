"""Kill an owned controller during prepared VRM playback, then verify recovery.

Uses a copy of a qualification world and its archived skeleton. No ARDY
generation, account access, microphone, or existing controller is used.
"""

import argparse
import copy
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

from promethee.appearance_process import AppearancePreparation
from promethee.avatar_reach import PixivArmReach
from promethee.execution import ExecutionService
from promethee.kinematic import KinematicController
from promethee.migrations import migrate
from promethee.runtime import Runtime


class SkeletonOnlyWorker:
    pending = None

    def __init__(self, output, skeleton):
        self.output = output
        self.events = deque([{"type": "ready", "skeleton": skeleton}])

    def poll(self):
        return self.events.popleft() if self.events else None

    def submit(self, job):
        raise AssertionError("Recovery must not generate or replay motor work.")

    def close(self):
        pass


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def observation(world):
    return {key: copy.deepcopy(world[key]) for key in ("avatar", "objects", "pose", "appearance")}


def controller(args, service):
    root = Path(__file__).resolve().parents[2]
    result = KinematicController(
        service,
        SkeletonOnlyWorker(args.output, json.loads(args.skeleton.read_text(encoding="utf-8"))),
        object_interactions=True,
        arm_reach_check=PixivArmReach().check,
        appearance_preparation=AppearancePreparation(
            avatar=args.avatar,
            script=root / "web/avatar/measure-feet.mjs",
            output=args.output / "appearance",
        ),
    )
    deadline = time.monotonic() + 30
    while not result.ready:
        result.tick()
        if time.monotonic() > deadline:
            result.close()
            raise TimeoutError("Prepared controller did not become ready.")
        time.sleep(0.02)
    return result


def child(args):
    service = ExecutionService(Runtime(args.output / "world.sqlite3"))
    driver = controller(args, service)
    try:
        world = service.get_world()
        held = world["avatar"]["holding"]
        if held is None:
            if not world["objects"]:
                raise ValueError("Use a qualification world containing an object.")
            action = {"kind": "take", "args": {"object_id": sorted(world["objects"])[0]}}
        else:
            target = list(world["objects"][held]["position"])
            target[1] -= 0.02
            target[2] += 0.02
            action = {"kind": "place", "args": {"position": target}}
        service.submit("crash-place", world["revision"], action)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            driver.tick()
            item = service.get("crash-place")
            if item["status"] not in {"accepted", "running"}:
                raise AssertionError(item)
            if (
                driver.trajectory is not None
                and driver.frame >= 10
                and item.get("observation") == driver.observation
            ):
                save(args.output / "before.json", driver.observation)
                save(args.output / "running.json", item)
                save(args.output / "kill-point.json", {"frame": driver.frame})
                print("CHECKPOINT_READY", flush=True)
                sys.stdin.readline()  # Parent kills this process before any cleanup.
                raise AssertionError("Parent did not kill the owned process.")
            time.sleep(0.02)
        raise TimeoutError("No prepared running checkpoint reached.")
    finally:
        driver.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--skeleton", type=Path, required=True)
    parser.add_argument("--avatar", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        child(args)
        return
    args.output.mkdir(parents=True, exist_ok=False)
    source = args.source.resolve()
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
        with sqlite3.connect(args.output / "world.sqlite3") as replica:
            original.backup(replica)
    migrate(args.output / "world.sqlite3", args.output / "before-migration.sqlite3")
    service = ExecutionService(Runtime(args.output / "world.sqlite3"))
    world = service.get_world()
    if world.get("session_kind") != "qualification" or world.get("appearance") is None:
        raise ValueError("Source must be a qualification world with prepared appearance.")
    root = Path(__file__).resolve().parents[2]
    sources = args.output / "sources"
    sources.mkdir()
    for file in [Path(__file__), *sorted((root / "src/promethee").glob("*.py"))]:
        shutil.copy2(file, sources / file.name)
    save(args.output / "config.json", {k: str(v) for k, v in vars(args).items()})
    save(
        args.output / "source-hashes.json",
        {
            str(file): hashlib.sha256(file.read_bytes()).hexdigest()
            for file in (source, args.skeleton, args.avatar)
        },
    )
    command = [
        sys.executable,
        "-X",
        "utf8",
        str(Path(__file__).resolve()),
        *sys.argv[1:],
        "--child",
    ]
    with (args.output / "child.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 40
            while not (args.output / "kill-point.json").exists():
                if process.poll() is not None:
                    raise RuntimeError("Owned controller exited early; inspect child.log.")
                if time.monotonic() > deadline:
                    raise TimeoutError("Owned controller checkpoint deadline exceeded.")
                time.sleep(0.05)
            process.kill()
            process.wait(timeout=5)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            process.stdin.close()
    before = json.loads((args.output / "before.json").read_text(encoding="utf-8"))
    deadline = time.monotonic() + 8
    while service.get("crash-place")["status"] != "interrupted":
        service.get_world()  # Reconcile lease expiry through the public service.
        if time.monotonic() > deadline:
            raise TimeoutError("Killed controller lease did not expire.")
        time.sleep(0.05)
    lost = service.get_world()
    assert lost["body"]["status"] == "unconfirmed"
    assert observation(lost) == before
    save(args.output / "lost-world.json", lost)
    driver = controller(args, service)
    try:
        for _ in range(10):
            driver.tick()
            time.sleep(0.02)
        after = service.get_world()
        assert driver.observation == observation(after) == before
        assert after["body"]["status"] == "confirmed"
        assert service.get("crash-place")["status"] == "interrupted"
        assert driver.active is None and driver.worker.pending is None
        save(args.output / "after-world.json", after)
        save(args.output / "events.json", service.events())
        import numpy as np

        frames = [before] * 40 + [observation(after)] * 40
        save(args.output / "recovery-replay.json", frames)
        np.savez_compressed(
            args.output / "recovery-replay.npz",
            posed_joints=np.asarray([frame["pose"]["positions"] for frame in frames]),
            global_rot_mats=np.asarray([frame["pose"]["rotations"] for frame in frames]),
            fps=20,
        )
        save(
            args.output / "report.json",
            {
                "qualification_only": True,
                "owned_process_returncode": process.returncode,
                "kill_frame": json.loads((args.output / "kill-point.json").read_text())["frame"],
                "checkpoint_preserved": True,
                "body_after_loss": "unconfirmed",
                "body_after_recovery": "confirmed",
                "old_execution_status": "interrupted",
                "automatic_replay": False,
                "new_ardy_generation": False,
                "visual_review": "pending",
            },
        )
        print((args.output / "report.json").read_text(), flush=True)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
