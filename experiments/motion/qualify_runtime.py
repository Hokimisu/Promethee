"""Exercise the real Windows/Linux runtime; outputs are technical qualification only."""

import argparse
import copy
import hashlib
import json
import shutil
import time
from pathlib import Path

import promethee.kinematic as kinematic_module
from promethee.execution import ExecutionService
from promethee.kinematic import KinematicController
from promethee.motion_process import start_ardy_process
from promethee.runtime import Runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ardy-python", required=True)
    parser.add_argument("--checkpoint-root", required=True)
    parser.add_argument("--wsl")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--first-target", type=float, nargs=2, required=True)
    parser.add_argument("--second-target", type=float, nargs=2, required=True)
    parser.add_argument("--avatar", type=Path, help="Prepare the pinned VRM before playback.")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(
        Path(__file__).with_name("runtime-criteria.json"), args.output / "criteria.json"
    )
    shutil.copyfile(__file__, args.output / "qualification-source.py")
    source_folder = Path(kinematic_module.__file__).parent
    for name in (
        "kinematic.py",
        "ardy_worker.py",
        "ardy_geometry.py",
        "ardy_contacts.py",
        "motion_process.py",
        "appearance_process.py",
        "appearance_checkpoint.py",
        "prepared_avatar.py",
        "avatar_reach.py",
        "avatar_rotation.py",
        "pixiv_arm_profile.json",
    ):
        shutil.copyfile(source_folder / name, args.output / name)
    if args.avatar:
        web_source = Path(__file__).resolve().parents[2] / "web/avatar"
        web_archive = args.output / "web-sources"
        web_archive.mkdir()
        for path in [
            *web_source.glob("*.js"),
            *web_source.glob("*.mjs"),
            web_source / "package-lock.json",
        ]:
            shutil.copyfile(path, web_archive / path.name)
        (args.output / "avatar-sha256.txt").write_text(
            hashlib.sha256(args.avatar.read_bytes()).hexdigest(), encoding="utf-8"
        )
    (args.output / "purpose.json").write_text(
        json.dumps(
            {
                "purpose": "held-out motor qualification; exclude this world from agent memory",
                "configuration": {
                    key: str(value) if isinstance(value, Path) else value
                    for key, value in vars(args).items()
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    service = ExecutionService(
        Runtime(args.output / "world.sqlite3", data_origin="session", session_kind="qualification")
    )
    worker = start_ardy_process(
        python=args.ardy_python,
        checkpoint_root=args.checkpoint_root,
        output=args.output / "motions",
        wsl=args.wsl,
    )
    preparation = None
    if args.avatar:
        from promethee.appearance_process import AppearancePreparation

        preparation = AppearancePreparation(
            avatar=args.avatar,
            script=Path(__file__).resolve().parents[2] / "web/avatar/measure-feet.mjs",
            output=args.output / "appearance",
        )
    try:
        controller = KinematicController(
            service, worker, seed=args.seed, appearance_preparation=preparation
        )
    except Exception:
        worker.close()
        if preparation is not None:
            preparation.close()
        raise
    results = []
    observations = []
    sample_times = []
    trial_started = time.monotonic()

    def spin_until(predicate, seconds=90):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            controller.tick()
            if controller.ready:
                observations.append(copy.deepcopy(controller.observation))
                sample_times.append(time.monotonic() - trial_started)
            if predicate():
                return
            time.sleep(0.05)
        raise TimeoutError("Runtime qualification timed out.")

    try:
        spin_until(lambda: controller.ready, seconds=180)
        actions = [
            {"kind": "move", "args": {"position": args.first_target}},
            {"kind": "posture", "args": {"name": "arms_raised"}},
            {"kind": "posture", "args": {"name": "standing"}},
            {"kind": "move", "args": {"position": args.second_target}},
        ]
        for index, action in enumerate(actions):
            request_id = f"qualification-{index}"
            state = service.get_world()
            service.submit(request_id, state["revision"], action)
            started = time.monotonic()
            spin_until(
                lambda request_id=request_id: (
                    service.get(request_id)["status"]
                    in {"completed", "failed", "interrupted", "rejected"}
                )
            )
            item = service.get(request_id)
            result = {
                "request_id": request_id,
                "action": action,
                "status": item["status"],
                "elapsed_seconds": time.monotonic() - started,
                "error": item.get("error"),
                "observed_position": service.get_world()["avatar"]["position"],
            }
            results.append(result)
            print(json.dumps(result), flush=True)
    finally:
        controller.close()
        (args.output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        (args.output / "observations.json").write_text(
            json.dumps({"sample_times_seconds": sample_times, "observations": observations}),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
