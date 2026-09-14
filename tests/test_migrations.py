import copy
import json
import sqlite3

import pytest

from promethee.catalog import INITIAL_WORLD
from promethee.migrations import migrate, read_world
from promethee.runtime import Runtime


@pytest.fixture
def old_database(tmp_path):
    path = tmp_path / "old.sqlite3"
    world = copy.deepcopy(INITIAL_WORLD)
    world.pop("revision")
    world.pop("data_origin")
    world.update(schema_version=1, world_id="historical-world")
    world["avatar"]["position"] = [1, 0]
    steps = [
        {"kind": "move", "args": {"position": [1, 0]}},
        {"kind": "move", "args": {"position": [2, 0]}},
    ]
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE world (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT);
            CREATE TABLE commands (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE, action TEXT NOT NULL,
                result TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE activities (id TEXT PRIMARY KEY, data TEXT NOT NULL);
        """)
        conn.execute("INSERT INTO world VALUES (1, ?)", (json.dumps(world),))
        conn.execute(
            "INSERT INTO commands(request_id,action,result,created_at) VALUES (?,?,?,?)",
            (
                "activity-old-plan-0",
                json.dumps(steps[0]),
                '{"ok":true}',
                "2026-09-15T00:00:00+00:00",
            ),
        )
        conn.execute(
            "INSERT INTO commands(request_id,action,result,created_at) VALUES (?,?,?,?)",
            (
                "rejected",
                '{"kind":"take","args":{"object_id":"absent"}}',
                '{"ok":false,"error":"Unknown object"}',
                "2026-09-15T00:00:01+00:00",
            ),
        )
        conn.execute(
            "INSERT INTO activities VALUES (?,?)",
            (
                "old-plan",
                json.dumps({"id": "old-plan", "steps": steps, "cursor": 1, "status": "paused"}),
            ),
        )
    return path


def contents(path):
    with sqlite3.connect(path) as conn:
        return list(conn.iterdump())


def test_opening_old_world_requires_explicit_migration(old_database):
    before = contents(old_database)
    with pytest.raises(ValueError, match="migrate"):
        Runtime(old_database)
    assert contents(old_database) == before


def test_backup_preserves_history_and_migrated_plan_resumes(old_database, tmp_path):
    before = contents(old_database)
    backup = tmp_path / "backup.sqlite3"
    result = migrate(old_database, backup)
    assert result["migrated"]
    assert contents(backup) == before
    runtime = Runtime(old_database)
    assert runtime.snapshot()["data_origin"] == "legacy"
    assert runtime.snapshot()["revision"] == 0
    assert runtime.snapshot()["world_id"] == "historical-world"
    with pytest.raises(ValueError, match="session"):
        runtime.require_session()
    assert len(runtime.events()) == 2
    assert runtime.events()[-1]["result"]["ok"] is False
    assert runtime.activity("old-plan")["cursor"] == 1
    runtime.set_paused("old-plan", False)
    assert runtime.advance("old-plan")["status"] == "completed"
    assert runtime.snapshot()["avatar"]["position"] == [2, 0]
    assert runtime.snapshot()["revision"] == 1
    after = contents(old_database)
    assert not migrate(old_database, backup)["migrated"]
    assert contents(old_database) == after
    assert contents(backup) == before


def test_migration_failure_rolls_back_without_losing_backup(old_database, tmp_path):
    with sqlite3.connect(old_database) as conn:
        conn.execute("""CREATE TRIGGER fail_migration BEFORE UPDATE ON world
            BEGIN SELECT RAISE(ABORT, 'simulated migration failure'); END;""")
    before = contents(old_database)
    backup = tmp_path / "backup.sqlite3"
    with pytest.raises(sqlite3.IntegrityError, match="simulated migration failure"):
        migrate(old_database, backup)
    assert contents(old_database) == before
    assert contents(backup) == before


def test_existing_backup_is_never_overwritten(old_database, tmp_path):
    backup = tmp_path / "backup.sqlite3"
    backup.write_bytes(b"preserve me")
    before = contents(old_database)
    with pytest.raises(FileExistsError):
        migrate(old_database, backup)
    assert backup.read_bytes() == b"preserve me"
    assert contents(old_database) == before


def test_unknown_schema_is_refused_without_creating_backup(old_database, tmp_path):
    with sqlite3.connect(old_database) as conn:
        world = read_world(conn)
        world["schema_version"] = 999
        conn.execute("UPDATE world SET data=?", (json.dumps(world),))
    before = contents(old_database)
    with pytest.raises(ValueError, match="No migration"):
        migrate(old_database, tmp_path / "backup.sqlite3")
    with pytest.raises(ValueError, match="Unsupported"):
        Runtime(old_database)
    assert contents(old_database) == before
    assert not (tmp_path / "backup.sqlite3").exists()
