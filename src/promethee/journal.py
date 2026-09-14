"""Export observations of successful logical actions; never synthesize private thoughts."""

import json
from pathlib import Path


def export_journal(runtime, vault):
    world = runtime.snapshot()
    world_id = world["world_id"]
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
            f"data_origin: {world['data_origin']}\n"
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
    # Body events have their own IDs and explicit outcomes; an accepted request is
    # not an observation of success. Reading this journal never drives the controller.
    after = 0
    while True:
        with runtime.connection() as conn:
            rows = conn.execute(
                "SELECT seq,data FROM execution_events WHERE seq>? ORDER BY seq LIMIT 100",
                (after,),
            ).fetchall()
        if not rows:
            break
        for seq, data in rows:
            after = seq
            event = json.loads(data)
            if event["kind"] not in {"completed", "failed", "cancelled", "interrupted", "rejected"}:
                continue
            execution = event["execution"]
            request_id = execution["request_id"]
            path = folder / f"execution-{seq:06d}-{request_id}.md"
            record = json.dumps(event, ensure_ascii=False, indent=2)
            text = (
                "---\nsource: promethee-execution-runtime\n"
                f"data_origin: {world['data_origin']}\nworld_id: {world_id}\n"
                f"event_id: execution-{seq}\nrequest_id: {request_id}\n"
                f"recorded_at: {event['recorded_at']}\n"
                f"controller_mode: {execution.get('source') or 'unavailable'}\n"
                f"execution_status: {execution['status']}\nkind: execution-outcome\n---\n\n"
                f"# {execution['status']}\n\n"
                "Résultat du registre d'exécution. La provenance distingue le test logique, "
                "le contrôle cinématique et le contrôle physique ; une demande acceptée "
                "n'est pas une réussite.\n\n"
                f"    {record.replace(chr(10), chr(10) + '    ')}\n"
            )
            try:
                with path.open("x", encoding="utf-8", newline="\n") as output:
                    output.write(text)
            except FileExistsError:
                continue
            count += 1
    return count
