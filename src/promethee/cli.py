import argparse
import json
from pathlib import Path

from promethee.catalog import CATALOG
from promethee.demo import ACTIVITY_ID, STEPS
from promethee.execution import ExecutionService
from promethee.journal import export_journal
from promethee.migrations import migrate
from promethee.runtime import Runtime
from promethee.world import ActionError


def main():
    parser = argparse.ArgumentParser(description="Promethee: local logical-world prototype.")
    parser.add_argument("--data-dir", type=Path, default=Path(".local/promethee"))
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Run the scripted welcome activity.")
    demo.add_argument("--pause-after", type=int, choices=range(1, len(STEPS)))
    demo.add_argument("--resume", action="store_true")
    commands.add_parser("world", help="Print the authoritative world snapshot.")
    commands.add_parser(
        "init-session", help="Create a new interactive world, without a body or model."
    )
    memory_init = commands.add_parser(
        "memory-init", help="Bind a new empty vault to an interactive world."
    )
    memory_init.add_argument("--vault", type=Path, required=True)
    memory_search = commands.add_parser(
        "memory-search", help="Search registered Markdown memories."
    )
    memory_search.add_argument("--vault", type=Path, required=True)
    memory_search.add_argument("--query", default="")
    memory_export = commands.add_parser(
        "memory-export", help="Complete pending registered note exports."
    )
    memory_export.add_argument("--vault", type=Path, required=True)
    initiative = commands.add_parser("initiative", help="Explicit session initiative controls.")
    controls = initiative.add_subparsers(dest="initiative_command", required=True)
    enable = controls.add_parser("configure")
    enable.add_argument("--budget", type=int, required=True)
    enable.add_argument("--interval", type=float)
    for control in ("pause", "resume", "status"):
        controls.add_parser(control)
    replenish = controls.add_parser("add-budget")
    replenish.add_argument("--calls", type=int, required=True)
    commands.add_parser(
        "catalog", help="List logical assets and capabilities without changing data."
    )
    act = commands.add_parser("act", help="Execute one logical action from a UTF-8 JSON file.")
    act.add_argument("--request-id", required=True)
    act.add_argument("--file", type=Path, required=True)
    migration = commands.add_parser(
        "migrate", help="Migrate an old world with a new verified backup."
    )
    migration.add_argument("--backup", type=Path, required=True)
    journal = commands.add_parser("journal", help="Export successful actions as Markdown.")
    journal.add_argument("--vault", type=Path, default=Path(".local/vault"))
    run = commands.add_parser("run", help="Open a session with the real kinematic body.")
    from promethee.run import configure

    configure(run)
    chat = commands.add_parser("chat", help="Converse through the isolated native Hermes worker.")
    from promethee.chat import configure as configure_chat

    configure_chat(chat)
    voice = commands.add_parser("voice", help="Push-to-talk diagnostic through the same Hermes.")
    from promethee.voice import configure as configure_voice

    configure_voice(voice)
    submit = commands.add_parser("submit", help="Submit an asynchronous body action.")
    submit.add_argument("--request-id", required=True)
    submit.add_argument("--expected-revision", type=int, required=True)
    submit.add_argument("--file", type=Path, required=True)
    for name in ("execution", "cancel"):
        command = commands.add_parser(name)
        command.add_argument("--request-id", required=True)
    args = parser.parse_args()
    exit_code = 0
    try:
        if args.command == "initiative":
            from promethee.initiative import Initiative

            runtime = Runtime(args.data_dir / "world.sqlite3", create=False)
            manager = Initiative(ExecutionService(runtime))
            if args.initiative_command == "configure":
                result = manager.configure(budget=args.budget, interval=args.interval)
            elif args.initiative_command in {"pause", "resume"}:
                result = manager.update(paused=args.initiative_command == "pause")
            elif args.initiative_command == "add-budget":
                result = manager.update(add_budget=args.calls)
            else:
                result = manager.observe()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "init-session":
            if (args.data_dir / "world.sqlite3").exists():
                raise ValueError("Choose a new session directory; existing data is never promoted.")
            runtime = Runtime(
                args.data_dir / "world.sqlite3", data_origin="session", session_kind="interactive"
            )
            print(
                json.dumps(
                    {"world_id": runtime.snapshot()["world_id"], "session_kind": "interactive"}
                )
            )
            return 0
        if args.command in {"memory-init", "memory-search", "memory-export"}:
            from promethee.memory import MemoryStore, initialize_vault

            runtime = Runtime(args.data_dir / "world.sqlite3", create=False)
            if args.command == "memory-init":
                result = {"vault": str(initialize_vault(runtime, args.vault))}
            else:
                memory = MemoryStore(ExecutionService(runtime), args.vault)
                if args.command == "memory-search":
                    result = memory.search(args.query)
                else:
                    memory.export_pending()
                    result = {"exported": True}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "voice":
            from promethee.voice import run_voice

            try:
                run_voice(args)
            except KeyboardInterrupt:
                pass
            return 0
        if args.command == "chat":
            from promethee.chat import run_chat

            try:
                run_chat(args)
            except KeyboardInterrupt:
                pass
            return 0
        if args.command == "run":
            from promethee.run import run_session

            try:
                run_session(args)
            except KeyboardInterrupt:
                pass
            return 0
        if args.command == "catalog":
            print(json.dumps(CATALOG, ensure_ascii=False, indent=2))
            return 0
        if args.command == "migrate":
            result = migrate(args.data_dir / "world.sqlite3", args.backup)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        action = None
        if args.command in {"act", "submit"}:
            action = json.loads(args.file.read_text(encoding="utf-8"))
        if args.command in {"submit", "execution", "cancel"}:
            if not (args.data_dir / "world.sqlite3").is_file():
                raise ValueError("Open a world before controlling its body.")
        runtime = Runtime(args.data_dir / "world.sqlite3")
        if args.command == "submit":
            result = ExecutionService(runtime).submit(
                args.request_id, args.expected_revision, action
            )
            exit_code = 1 if result["status"] == "rejected" else 0
        elif args.command in {"execution", "cancel"}:
            service = ExecutionService(runtime)
            operation = service.get if args.command == "execution" else service.cancel
            result = operation(args.request_id)
        elif args.command == "act":
            result = runtime.execute(args.request_id, action)
            exit_code = 0 if result["ok"] else 1
        elif args.command == "world":
            result = ExecutionService(runtime).get_world()
        elif args.command == "journal":
            result = {
                "notes_created": export_journal(runtime, args.vault),
                "vault": str(args.vault),
            }
        else:
            activity = runtime.start_activity(ACTIVITY_ID, STEPS)
            if args.resume and activity["status"] == "paused":
                activity = runtime.set_paused(ACTIVITY_ID, False)
            while activity["status"] == "running":
                if args.pause_after is not None and activity["cursor"] >= args.pause_after:
                    activity = runtime.set_paused(ACTIVITY_ID, True)
                    break
                activity = runtime.advance(ACTIVITY_ID)
            result = {k: v for k, v in activity.items() if k != "steps"}
            if activity["status"] == "failed":
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 1
    except (ActionError, ValueError, OSError, UnicodeError) as exc:
        parser.exit(2, f"Error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
