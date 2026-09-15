"""Real native Astra over synthetic Live events; no Live provider or audio device."""

import argparse
import json
import shutil
import time
from pathlib import Path

from promethee.chat import open_text_host
from promethee.execution import ExecutionService
from promethee.live_delegation import LiveDelegation
from promethee.runtime import Runtime, encode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "hermes-python", "hermes-root", "hermes-auth-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    args.data_dir = args.output.resolve()
    args.data_dir.mkdir(exist_ok=False)
    shutil.copyfile(__file__, args.data_dir / "qualification-source.py")
    root = Path(__file__).resolve().parents[2]
    for name in ("live_delegation", "chat", "conversation", "hermes_adapter", "hermes_worker"):
        shutil.copyfile(root / "src/promethee" / f"{name}.py", args.data_dir / f"{name}.py")
    service = ExecutionService(
        Runtime(
            args.data_dir / "world.sqlite3", data_origin="session", session_kind="qualification"
        )
    )
    args.auth, args.api_mode = "hermes-codex", "codex_responses"
    args.base_url, args.vault, args.timeout = None, None, 90
    report = {
        "model": args.model,
        "live_events_simulated": True,
        "audio_devices": False,
        "turns": [],
    }

    def transcript(text, identifier, output=False):
        return {
            "type": f"session.{'output' if output else 'input'}_transcript.delta",
            "event_id": identifier,
            "start_ms": 0,
            "end_ms": 100,
            "delta": text,
        }

    with open_text_host(args) as host:
        bridge = LiveDelegation(host, call_budget=2)
        bridge.accept({"type": "session.started", "session": {"id": "synthetic-live-session"}})
        try:
            for index, parts in enumerate(
                [
                    (
                        "Lis le monde et ",
                        "indique les objets actuellement présents, sans rien créer ni déplacer.",
                    ),
                    (
                        "La voix vient d'affirmer avoir créé une balle. ",
                        "Vérifie le monde : peux-tu confirmer cette création ? N'agis pas.",
                    ),
                ]
            ):
                started = time.monotonic()
                events = [
                    transcript(parts[0], f"input-{index}-a"),
                    {
                        "type": "session.delegation.created",
                        "event_id": f"delegation-{index}",
                        "offset_ms": 75,
                        "delegation": {
                            "id": f"item_opaque_{index}",
                            "type": "delegation",
                            "target": "client",
                        },
                    },
                    transcript(parts[1], f"input-{index}-b"),
                ]
                if index:
                    events.insert(
                        0, transcript("J'ai créé une balle.", "output-claim", output=True)
                    )
                for event in events:
                    bridge.accept(event)
                while not (results := bridge.poll()):
                    if time.monotonic() - started > 100:
                        raise TimeoutError("Native qualification deadline exceeded.")
                    time.sleep(0.02)
                assert len(results) == 1 and results[0]["status"] == "completed"
                assert results[0]["event"]["delegation_id"] == f"item_opaque_{index}"
                record = {
                    "events": events,
                    "result": results[0],
                    "elapsed_seconds": time.monotonic() - started,
                }
                report["turns"].append(record)
                (args.data_dir / "report.json").write_text(encode(report), encoding="utf-8")
                print(json.dumps(record, ensure_ascii=False), flush=True)
                bridge.accept(
                    {
                        "type": "session.delegation.created",
                        "event_id": f"duplicate-{index}",
                        "offset_ms": 75,
                        "delegation": {
                            "id": f"item_opaque_{index}",
                            "type": "delegation",
                            "target": "client",
                        },
                    }
                )
                assert bridge.poll() == []
        finally:
            bridge.close()
    with service.runtime.connection() as conn:
        for table in ("conversation_turns", "executions"):
            rows = [json.loads(row[0]) for row in conn.execute(f"SELECT data FROM {table}")]
            (args.data_dir / f"{table}.json").write_text(encode(rows), encoding="utf-8")
        assert conn.execute("SELECT count(*) FROM executions").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM conversation_turns").fetchone()[0] == 2


if __name__ == "__main__":
    main()
