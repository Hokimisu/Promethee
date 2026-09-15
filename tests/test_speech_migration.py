"""Voice receipts migrate explicitly without inventing past playback."""

import json
import sqlite3

import pytest

from promethee.conversation import ConversationStore
from promethee.execution import ExecutionService
from promethee.migrations import migrate, read_world
from promethee.runtime import Runtime, encode


@pytest.mark.parametrize("fail", [False, True])
def test_v10_voice_migration_preserves_history_and_has_verified_backup(tmp_path, fail):
    runtime = Runtime(
        tmp_path / "world.sqlite3", data_origin="session", session_kind="qualification"
    )
    store = ConversationStore(ExecutionService(runtime))
    opened = store.begin("Historic message")
    with runtime.connection() as conn:
        world = read_world(conn)
        world["schema_version"] = 10
        conn.execute("UPDATE world SET data=? WHERE id=1", (encode(world),))
        record = json.loads(conn.execute("SELECT data FROM conversation_turns").fetchone()[0])
        record.pop("speech_delivery")
        conn.execute("UPDATE conversation_turns SET data=?", (encode(record),))
        if fail:
            conn.execute(
                "CREATE TRIGGER fail_voice BEFORE UPDATE ON conversation_turns "
                "BEGIN SELECT RAISE(ABORT, 'voice migration rollback'); END;"
            )
        before = list(conn.iterdump())
    backup = tmp_path / "v10-backup.sqlite3"
    if fail:
        with pytest.raises(sqlite3.IntegrityError, match="voice migration rollback"):
            migrate(runtime.path, backup)
        with runtime.connection() as conn:
            assert list(conn.iterdump()) == before
    else:
        assert migrate(runtime.path, backup)["schema_version"] == 11
        assert Runtime(runtime.path).snapshot() == {**world, "schema_version": 11}
        with runtime.connection() as conn:
            status, data = conn.execute("SELECT status,data FROM conversation_turns").fetchone()
            assert status == "running"
            assert json.loads(data) == {**record, "speech_delivery": None}
        assert opened["turn_id"] == record["turn_id"]
        assert not migrate(runtime.path, tmp_path / "unused.sqlite3")["migrated"]
    with sqlite3.connect(backup) as conn:
        assert list(conn.iterdump()) == before
