"""Export observations of successful logical actions; never synthesize private thoughts."""

import json
from pathlib import Path


def export_journal(runtime, vault):
    world_id = runtime.snapshot()["world_id"]
    folder = Path(vault) / "Promethee" / "Observed" / world_id
    folder.mkdir(parents=True, exist_ok=True)
    count = 0
    for event in runtime.events():
        if not event["result"]["ok"]:
            continue
        path = folder / f"{event['seq']:06d}-{event['request_id']}.md"
        # Exports are append-only. Preserve a user's later edits in Obsidian.
        if path.exists():
            continue
        record = json.dumps(event["action"], ensure_ascii=False, indent=2)
        text = (
            "---\n"
            "source: promethee-logical-runtime\n"
            f"world_id: {world_id}\n"
            f"event_id: {event['seq']}\n"
            f"request_id: {event['request_id']}\n"
            f"recorded_at: {event['created_at']}\n"
            "kind: observed-action\n"
            "---\n\n"
            f"# {event['action']['kind']}\n\n"
            "Action validée dans le monde logique. Aucune exécution physique ou 3D attestée.\n\n"
            f"    {record.replace(chr(10), chr(10) + '    ')}\n"
        )
        # Exclusive creation also preserves edits when two exporters run concurrently.
        try:
            with path.open("x", encoding="utf-8", newline="\n") as output:
                output.write(text)
        except FileExistsError:
            continue
        count += 1
    return count
