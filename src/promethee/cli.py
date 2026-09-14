import argparse
import json
from pathlib import Path

from promethee.demo import ACTIVITY_ID, STEPS
from promethee.journal import export_journal
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
    journal = commands.add_parser("journal", help="Export successful actions as Markdown.")
    journal.add_argument("--vault", type=Path, default=Path(".local/vault"))
    args = parser.parse_args()
    runtime = Runtime(args.data_dir / "world.sqlite3")
    try:
        if args.command == "world":
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
    except (ActionError, ValueError) as exc:
        parser.exit(2, f"Error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
