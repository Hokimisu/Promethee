"""Exercise the real Windows/Linux runtime; outputs are technical qualification only."""

import argparse
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
    ):
        shutil.copyfile(source_folder / name, args.output / name)
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
    controller = KinematicController(service, worker, seed=args.seed)
    results = []

    def spin_until(predicate, seconds=90):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            controller.tick()
            if predicate():
                return
            time.sleep(0.025)
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


if __name__ == "__main__":
    main()
