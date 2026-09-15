"""Exercise the real native Hermes/ChatGPT host on a fresh qualification world.

Three bounded real model calls verify text, world reading and history after
host restart. This does not qualify body actions, voice, or personal memory.
"""

import argparse
import json
import shutil
import sqlite3
import time
from pathlib import Path

from promethee.chat import open_text_host
from promethee.runtime import Runtime

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--hermes-python", type=Path, required=True)
parser.add_argument("--hermes-root", type=Path, required=True)
parser.add_argument("--hermes-auth-root", type=Path, required=True)
parser.add_argument("--model", required=True)
args = parser.parse_args()
args.data_dir = args.output.resolve()
args.data_dir.mkdir(exist_ok=False)
args.auth, args.api_mode = "hermes-codex", "codex_responses"
args.base_url, args.vault, args.timeout = None, None, 90
root = Path(__file__).resolve().parents[2]
shutil.copyfile(__file__, args.data_dir / "qualification-source.py")
for source in ("chat.py", "hermes_worker.py", "hermes_adapter.py", "conversation.py"):
    shutil.copyfile(root / "src/promethee" / source, args.data_dir / source)
Runtime(args.data_dir / "world.sqlite3", data_origin="session", session_kind="qualification")
prompts = [
    "Bonjour. Pour cet essai technique, réponds simplement bonjour, sans outil ni action.",
    "Lis l’état actuel du monde avec l’outil disponible et décris ce qui est confirmé. "
    "Ne soumets aucune action.",
    "Quel était mon tout premier message dans cette conversation ? Cite-le exactement. "
    "Ne soumets aucune action.",
]
report = {"model_requested": args.model, "provider": "openai-codex", "turns": []}
for prompt in prompts:
    started = time.monotonic()
    with open_text_host(args) as host:
        turn_id = host.start(prompt)
        while (result := host.poll()) is None:
            time.sleep(0.05)
    entry = {
        "turn_id": turn_id,
        "prompt": prompt,
        "result": result,
        "elapsed_seconds": time.monotonic() - started,
    }
    report["turns"].append(entry)
    profile = args.hermes_auth_root / "profiles" / ("promethee-" + turn_id)
    shutil.copyfile(profile / "config.yaml", args.data_dir / (turn_id + "-profile.json"))
    (args.data_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(entry, ensure_ascii=False), flush=True)
    if result["status"] != "completed":
        raise SystemExit("Real Hermes turn failed; retained the diagnostic artifacts.")
with sqlite3.connect(args.data_dir / "world.sqlite3") as conn:
    history = [json.loads(row[0]) for row in conn.execute("SELECT data FROM conversation_turns")]
    (args.data_dir / "history.json").write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )
print("Review the archived tool calls and replies; no body or voice qualification is implied.")
