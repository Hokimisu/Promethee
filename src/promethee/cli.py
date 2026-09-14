import argparse
import json
from pathlib import Path

from promethee.catalog import CATALOG
from promethee.demo import ACTIVITY_ID, STEPS
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
    args = parser.parse_args()
    exit_code = 0
    try:
        if args.command == "catalog":
            print(json.dumps(CATALOG, ensure_ascii=False, indent=2))
            return 0
        if args.command == "migrate":
            result = migrate(args.data_dir / "world.sqlite3", args.backup)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        action = None
        if args.command == "act":
            action = json.loads(args.file.read_text(encoding="utf-8"))
        runtime = Runtime(args.data_dir / "world.sqlite3")
        if args.command == "act":
            result = runtime.execute(args.request_id, action)
            exit_code = 0 if result["ok"] else 1
        elif args.command == "world":
            result = runtime.snapshot()
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
