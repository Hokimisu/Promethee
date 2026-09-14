"""Explicit, backed-up SQLite migrations. Opening a runtime never migrates data."""

import json
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2


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
    """Preserve an exclusive backup before changing v1 metadata atomically."""
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
            if type(version) is not int or version != 1:
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
            world.update(schema_version=SCHEMA_VERSION, data_origin="legacy", revision=0)
            conn.execute(
                "UPDATE world SET data=? WHERE id=1",
                (json.dumps(world, ensure_ascii=False, sort_keys=True, allow_nan=False),),
            )
        return {"schema_version": SCHEMA_VERSION, "migrated": True, "backup": str(backup)}
    finally:
        conn.close()
