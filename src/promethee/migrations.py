"""Explicit, backed-up SQLite migrations. Opening a runtime never migrates data."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 10


def create_memory_tables(conn):
    conn.execute("CREATE TABLE memory_notes (note_id TEXT PRIMARY KEY, data TEXT NOT NULL)")


def create_conversation_tables(conn):
    conn.execute(
        "CREATE TABLE conversation_turns (seq INTEGER PRIMARY KEY AUTOINCREMENT, "
        "turn_id TEXT NOT NULL UNIQUE, status TEXT NOT NULL, data TEXT NOT NULL)"
    )


def create_execution_tables(conn):
    conn.execute(
        "CREATE TABLE executions (request_id TEXT PRIMARY KEY, "
        "status TEXT NOT NULL, data TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX one_active_execution ON executions ((1)) "
        "WHERE status IN ('accepted','running')"
    )
    conn.execute(
        "CREATE TABLE execution_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, "
        "request_id TEXT NOT NULL, data TEXT NOT NULL)"
    )
    conn.execute("CREATE TABLE controller (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)")
    conn.execute("INSERT INTO controller VALUES (1, ?)", (json.dumps({"session_id": None}),))


def _upgrade(conn, world):
    if world["schema_version"] == 1:
        world.update(schema_version=2, data_origin="legacy", revision=0)
    if world["schema_version"] == 2:
        create_execution_tables(conn)
        world.update(
            schema_version=3, body={"status": "unconfirmed", "observed_at": None, "source": None}
        )
    if world["schema_version"] == 3:
        # A floor-plane observation cannot attest an articulated body. Fence old drivers
        # and preserve unfinished requests as interrupted, never silently replay them.
        now = datetime.now(UTC).isoformat()
        for request_id, data in conn.execute(
            "SELECT request_id,data FROM executions WHERE status IN ('accepted','running')"
        ).fetchall():
            item = json.loads(data)
            item.update(
                status="interrupted",
                updated_at=now,
                error={"code": "schema_migrated", "message": "Reconcile the articulated body."},
            )
            conn.execute(
                "UPDATE executions SET status=?,data=? WHERE request_id=?",
                ("interrupted", json.dumps(item), request_id),
            )
            event = {"kind": "interrupted", "recorded_at": now, "execution": item}
            conn.execute(
                "INSERT INTO execution_events(request_id,data) VALUES (?,?)",
                (request_id, json.dumps(event)),
            )
        conn.execute("UPDATE controller SET data=? WHERE id=1", (json.dumps({"session_id": None}),))
        world.update(schema_version=4, pose=None)
        world["body"]["status"] = "unconfirmed"
    if world["schema_version"] == 4:
        world.update(schema_version=5, conversation=None)
    if world["schema_version"] == 5:
        create_conversation_tables(conn)
        # No old prompt or personal profile is imported. Fence an in-flight
        # pre-migration conversation, preserving every body observation/action.
        world.update(schema_version=6, conversation=None)
    if world["schema_version"] == 6:
        create_memory_tables(conn)
        # Never promote old qualification or unclassified session data into memory.
        world.update(schema_version=7, session_kind=None)
    if world["schema_version"] == 7:
        world.update(schema_version=8, initiative=None)
    if world["schema_version"] == 8:
        # Spatial object observations are optional. Never invent height,
        # orientation or a hand attachment for historical logical objects.
        world.update(schema_version=9)
    if world["schema_version"] == 9:
        # Historical Core poses do not establish an adapted visible pose.
        world.update(schema_version=10, appearance=None)


def read_world(conn):
    row = conn.execute("SELECT data FROM world WHERE id=1").fetchone()
    if row is None:
        raise ValueError("World snapshot is missing.")
    return json.loads(row[0])


def check_version(world):
    if world.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported world schema version {world.get('schema_version')!r}; "
            "run 'promethee migrate --backup <new-file>' explicitly."
        )


def migrate(path, backup):
    """Preserve an exclusive backup before upgrading a known schema atomically."""
    path, backup = Path(path).resolve(), Path(backup).resolve()
    # mode=rw prevents a typo from creating an empty source database.
    conn = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=10)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            world = read_world(conn)
            version = world.get("schema_version")
            if version == SCHEMA_VERSION:
                return {"schema_version": version, "migrated": False, "backup": None}
            if type(version) is not int or version not in (1, 2, 3, 4, 5, 6, 7, 8, 9):
                raise ValueError(f"No migration available from schema {version!r}.")
            if path == backup:
                raise ValueError("Backup must be a different, new file.")
            backup.parent.mkdir(parents=True, exist_ok=True)
            with backup.open("xb"):
                pass
            # A second reader copies the source while BEGIN IMMEDIATE excludes writers.
            # Backing up the writer connection inside its transaction would block.
            source = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
            saved = sqlite3.connect(backup)
            try:
                source.backup(saved)
                if saved.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Backup integrity check failed; migration cancelled.")
                if read_world(saved) != world:
                    raise ValueError("Backup does not match the source; migration cancelled.")
            finally:
                saved.close()
                source.close()
            _upgrade(conn, world)
            conn.execute(
                "UPDATE world SET data=? WHERE id=1",
                (json.dumps(world, ensure_ascii=False, sort_keys=True, allow_nan=False),),
            )
        return {"schema_version": SCHEMA_VERSION, "migrated": True, "backup": str(backup)}
    finally:
        conn.close()
