"""Explicit, backed-up SQLite migrations. Opening a runtime never migrates data."""

import json
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 3


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
            if type(version) is not int or version not in (1, 2):
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
