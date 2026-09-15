"""Observe three bounded native Astra initiative turns in two isolated worlds.

One world has no history or controller. The other uses real ARDY, one user
exchange, a pause across host restart, then controller shutdown. No desired
activity, memory, personality, or outcome is injected into the autonomous wake.
The audio path is not exercised. Review replies and any body actions separately.
"""

import argparse
import json
import shutil
import time
from pathlib import Path

from promethee.appearance_process import AppearancePreparation
from promethee.chat import open_text_host
from promethee.execution import ExecutionService
from promethee.initiative import Initiative
from promethee.kinematic import KinematicController
from promethee.motion_process import start_ardy_process
from promethee.runtime import Runtime, encode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "hermes-python", "hermes-root", "hermes-auth-root", "avatar"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--ardy-python", required=True)
    parser.add_argument("--checkpoint-root", required=True)
    parser.add_argument("--wsl")
    parser.add_argument("--seed", type=int, default=148123)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    shutil.copyfile(__file__, output / "qualification-source.py")
    sources = output / "sources"
    sources.mkdir()
    for name in (
        "chat",
        "hermes_worker",
        "hermes_adapter",
        "conversation",
        "initiative",
        "execution",
        "kinematic",
        "mcp_server",
    ):
        shutil.copyfile(root / "src/promethee" / f"{name}.py", sources / f"{name}.py")
    args.auth, args.api_mode = "hermes-codex", "codex_responses"
    args.base_url, args.vault, args.timeout = None, None, 90
    report = {"model_requested": args.model, "seed": args.seed, "worlds": []}
    for index in range(2):
        args.data_dir = output / f"world-{index + 1}"
        args.data_dir.mkdir()
        service = ExecutionService(
            Runtime(
                args.data_dir / "world.sqlite3", data_origin="session", session_kind="qualification"
            )
        )
        initiative = Initiative(service)
        controller = None
        entry = {"world_id": service.get_world()["world_id"], "turns": []}
        report["worlds"].append(entry)

        def pump(controller):
            if controller is not None and not controller.closed:
                controller.tick()
            time.sleep(0.05)

        def observe_turn(host, controller, entry, *, message=None):
            started = time.monotonic()
            if message is not None:
                host.start(message)
            while True:
                pump(controller)
                if message is None:
                    host.initiative_tick()
                result = host.poll()
                if result is not None:
                    item = {
                        "turn_id": host.turn_id,
                        "trigger": "user" if message else "initiative",
                        "elapsed_seconds": time.monotonic() - started,
                        "result": result,
                    }
                    entry["turns"].append(item)
                    (output / "report.json").write_text(encode(report), encoding="utf-8")
                    print(json.dumps(item, ensure_ascii=False), flush=True)
                    if result["status"] != "completed":
                        raise RuntimeError("Real initiative call did not complete.")
                    state = host.store.service.get_world()["initiative"]
                    if state is not None:
                        assert state["active_turn"] is None
                    return
                if time.monotonic() - started > 100:
                    raise TimeoutError("No bounded initiative result.")

        try:
            if index == 1:
                worker = start_ardy_process(
                    python=args.ardy_python,
                    checkpoint_root=args.checkpoint_root,
                    output=args.data_dir / "motions",
                    wsl=args.wsl,
                )
                preparation = AppearancePreparation(
                    avatar=args.avatar.resolve(),
                    script=root / "web/avatar/measure-feet.mjs",
                    output=args.data_dir / "appearance",
                )
                controller = KinematicController(
                    service, worker, seed=args.seed, appearance_preparation=preparation
                )
                deadline = time.monotonic() + 180
                while not controller.ready:
                    pump(controller)
                    if time.monotonic() > deadline:
                        raise TimeoutError("Real ARDY initialization.")
                entry["initial_capabilities"] = service.supported_actions()
            with open_text_host(args) as host:
                if index == 1:
                    observe_turn(
                        host,
                        controller,
                        entry,
                        message="Quelles capacités sont actuellement utilisables dans ce monde ?",
                    )
                initiative.configure(budget=index + 1, interval=1)
                observe_turn(host, controller, entry)
                initiative.update(paused=True)
            # The same world is reopened; a persisted pause must suppress dispatch.
            with open_text_host(args) as host:
                deadline = time.monotonic() + 1.2
                while time.monotonic() < deadline:
                    pump(controller)
                    assert host.initiative_tick() is None
                    assert host.poll() is None
                entry["pause_after_restart"] = initiative.observe()
                if index == 1:
                    controller.close()
                    entry["withdrawn_capabilities"] = service.supported_actions()
                    entry["world_after_shutdown"] = service.get_world()
                    initiative.update(paused=False)
                    observe_turn(host, controller, entry)
                else:
                    initiative.update(paused=False)
                deadline = time.monotonic() + 1.2
                while time.monotonic() < deadline:
                    pump(controller)
                    assert host.initiative_tick() is None
                    assert host.poll() is None
                entry["final_budget"] = initiative.observe()
                assert entry["final_budget"]["remaining"] == 0
                assert entry["final_budget"]["used"] == index + 1
        finally:
            if controller is not None:
                controller.close()
            if service.get_world()["initiative"] is not None:
                initiative.update(paused=True)
            with service.runtime.connection() as conn:
                for table in ("conversation_turns", "executions", "execution_events"):
                    records = [
                        json.loads(row[0]) for row in conn.execute(f"SELECT data FROM {table}")
                    ]
                    (args.data_dir / f"{table}.json").write_text(encode(records), encoding="utf-8")
            (output / "report.json").write_text(encode(report), encoding="utf-8")


if __name__ == "__main__":
    main()
