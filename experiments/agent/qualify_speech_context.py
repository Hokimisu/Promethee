"""Real Astra reasoning over an explicitly simulated interrupted-playback receipt.

This uses two native Hermes calls and no audio provider or audio device.
It verifies the receipt's availability after restart, not acoustic delivery.
"""

import argparse
import json
import shutil
import time
from pathlib import Path

from promethee.chat import open_text_host
from promethee.conversation import ConversationStore
from promethee.execution import ExecutionService
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
    for name in (
        "voice",
        "conversation",
        "execution",
        "mcp_server",
        "hermes_adapter",
        "hermes_worker",
    ):
        shutil.copyfile(root / "src/promethee" / f"{name}.py", args.data_dir / f"{name}.py")
    service = ExecutionService(
        Runtime(
            args.data_dir / "world.sqlite3", data_origin="session", session_kind="qualification"
        )
    )
    args.auth, args.api_mode = "hermes-codex", "codex_responses"
    args.base_url, args.vault, args.timeout = None, None, 90
    report = {"model": args.model, "audio_simulated": True, "turns": []}
    prompts = [
        "Pour cet essai technique isolé, réponds seulement : Bonjour, je suis disponible.",
        "Lis le résultat de diffusion de ta réponse précédente dans le monde. "
        "Peux-tu confirmer qu'elle m'a été dite entièrement ? Quels mots puis-je "
        "avoir entendus avec certitude ? Ne relance ni audio ni action.",
    ]
    for index, prompt in enumerate(prompts):
        started = time.monotonic()
        with open_text_host(args) as host:
            turn_id = host.start(prompt)
            while (result := host.poll()) is None:
                time.sleep(0.05)
        report["turns"].append(
            {
                "turn_id": turn_id,
                "prompt": prompt,
                "result": result,
                "elapsed_seconds": time.monotonic() - started,
            }
        )
        (args.data_dir / "report.json").write_text(encode(report), encoding="utf-8")
        print(json.dumps(report["turns"][-1], ensure_ascii=False), flush=True)
        if result["status"] != "completed":
            raise RuntimeError("Real Astra call failed.")
        if index == 0:
            # Explicit synthetic host events: no PCM or device was used.
            store = ConversationStore(service)
            for status in ("preparing", "playing", "interrupted"):
                store.speech_delivery(turn_id, "synthetic-playback-01", status)
    with service.runtime.connection() as conn:
        for table in ("conversation_turns", "executions"):
            rows = [json.loads(row[0]) for row in conn.execute(f"SELECT data FROM {table}")]
            (args.data_dir / f"{table}.json").write_text(encode(rows), encoding="utf-8")
        assert conn.execute("SELECT count(*) FROM executions").fetchone()[0] == 0


if __name__ == "__main__":
    main()
