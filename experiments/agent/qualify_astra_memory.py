"""Exercise native Hermes memory in two disposable worlds with six real calls.

Only synthetic user messages are supplied. Each fresh memory world is downgraded
to qualification data in finally, preventing its later use as personal memory.
Review the archived replies and tool calls; completion alone is not a semantic
pass. No body controller, voice device, or personal vault is used.
"""

import argparse
import json
import shutil
import time
from pathlib import Path

from promethee.chat import open_text_host
from promethee.execution import ExecutionService
from promethee.memory import MemoryStore, initialize_vault
from promethee.migrations import read_world
from promethee.runtime import Runtime, encode
from promethee.world import ActionError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hermes-python", type=Path, required=True)
    parser.add_argument("--hermes-root", type=Path, required=True)
    parser.add_argument("--hermes-auth-root", type=Path, required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(exist_ok=False)
    shutil.copyfile(__file__, output / "qualification-source.py")
    root = Path(__file__).resolve().parents[2]
    sources = output / "sources"
    sources.mkdir()
    for name in (
        "chat",
        "hermes_worker",
        "hermes_adapter",
        "conversation",
        "memory",
        "mcp_server",
        "execution",
    ):
        shutil.copyfile(root / "src/promethee" / f"{name}.py", sources / f"{name}.py")
    args.auth, args.api_mode = "hermes-codex", "codex_responses"
    args.base_url, args.timeout = None, 90
    report = {"model_requested": args.model, "provider": "openai-codex", "worlds": []}
    prompts = [
        [
            "Essai technique isolé. Cherche dans la mémoire les notes concernant le "
            "repère azur. Rapporte le résultat sans inventer de souvenir ni créer de note.",
            "Donnée fictive de cet essai : j'avais proposé de comparer un repère azur "
            "et un repère ambre ; cette proposition est suspendue. Enregistre une "
            "note de proposition sourcée sur ce message, sans lancer d'action.",
            "Correction de la donnée fictive : la comparaison concernait un repère "
            "vert et un repère ambre, pas azur. Enregistre une correction liée à la "
            "note précédente, sourcée sur ce message. Le projet reste suspendu.",
            "Recherche maintenant le repère azur dans la mémoire. Relis la source de "
            "la correction retrouvée, puis explique le contenu actuel et ce qui a "
            "été corrigé. Ne reprends pas le projet et n'écris pas de nouvelle note.",
            "Les repères évoqués dans les notes sont-ils présents dans le monde "
            "actuel ? Vérifie le monde et distingue proposition historique et "
            "observation. Ne crée ni objet, ni action, ni nouvelle note.",
        ],
        [
            "Essai technique isolé. Cherche les notes concernant le repère azur "
            "dans la mémoire de ce monde. Rapporte uniquement ce que les outils "
            "permettent de confirmer ; ne crée aucune note ni action.",
        ],
    ]
    for index, messages in enumerate(prompts):
        args.data_dir = output / f"world-{index + 1}"
        args.data_dir.mkdir()
        runtime = Runtime(
            args.data_dir / "world.sqlite3", data_origin="session", session_kind="interactive"
        )
        service = ExecutionService(runtime)
        entry = {"world_id": service.get_world()["world_id"], "turns": []}
        report["worlds"].append(entry)
        args.vault = args.data_dir / "vault"
        try:
            initialize_vault(runtime, args.vault)
            for message in messages:
                started = time.monotonic()
                # A fresh host each time verifies history and memory across restart.
                with open_text_host(args) as host:
                    turn_id = host.start(message)
                    while (result := host.poll()) is None:
                        time.sleep(0.05)
                turn = {
                    "turn_id": turn_id,
                    "prompt": message,
                    "result": result,
                    "elapsed_seconds": time.monotonic() - started,
                }
                entry["turns"].append(turn)
                profile = args.hermes_auth_root / "profiles" / ("promethee-" + turn_id)
                shutil.copyfile(profile / "config.yaml", args.data_dir / f"{turn_id}-profile.json")
                (output / "report.json").write_text(encode(report), encoding="utf-8")
                print(json.dumps(turn, ensure_ascii=False), flush=True)
                if result["status"] != "completed":
                    raise RuntimeError("Real memory turn failed; inspect retained artifacts.")
            with runtime.connection() as conn:
                for table in ("conversation_turns", "memory_notes", "executions"):
                    records = [
                        json.loads(row[0]) for row in conn.execute(f"SELECT data FROM {table}")
                    ]
                    (args.data_dir / f"{table}.json").write_text(encode(records), encoding="utf-8")
                entry["execution_count"] = conn.execute(
                    "SELECT count(*) FROM executions"
                ).fetchone()[0]
                entry["note_count"] = conn.execute("SELECT count(*) FROM memory_notes").fetchone()[
                    0
                ]
                assert entry["execution_count"] == 0
        finally:
            # Isolated development artifact only; never reclassify a user's world.
            with runtime.connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                world = read_world(conn)
                world.update(session_kind="qualification", conversation=None)
                world["revision"] += 1
                conn.execute("UPDATE world SET data=? WHERE id=1", (encode(world),))
            try:
                MemoryStore(service, args.vault)
            except ActionError:
                entry["quarantine_verified"] = True
            else:
                raise AssertionError("Qualification memory was not refused.")
            (output / "report.json").write_text(encode(report), encoding="utf-8")


if __name__ == "__main__":
    main()
