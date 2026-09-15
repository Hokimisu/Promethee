"""Persistence/fencing tests, without inference or model-written observations."""

import json
import sqlite3

import pytest

from promethee.conversation import ConversationStore
from promethee.execution import ExecutionService
from promethee.migrations import migrate, read_world
from promethee.runtime import Runtime
from promethee.world import ActionError


def setup(tmp_path):
    now = [100.0]
    service = ExecutionService(
        Runtime(tmp_path / "world.sqlite3", data_origin="session"), clock=lambda: now[0]
    )
    return ConversationStore(service), now


def answer(turn, message, text="Response"):
    return {
        "type": "result",
        "turn_id": turn["turn_id"],
        "failed": False,
        "interrupted": False,
        "text": text,
        "messages": [
            *turn["history"],
            {"role": "user", "content": message},
            {"role": "assistant", "content": text},
        ],
    }


def test_successful_native_history_survives_new_host(tmp_path):
    store, now = setup(tmp_path)
    turn = store.begin("First")
    result = answer(turn, "First")
    assert store.finish(turn["turn_id"], result) == "Response"
    replacement = ConversationStore(
        ExecutionService(Runtime(store.service.runtime.path, create=False), clock=lambda: now[0])
    )
    next_turn = replacement.begin("Second")
    assert next_turn["history"] == result["messages"]
    assert next_turn["session_id"] == turn["session_id"]
    assert store.service.events() == []


def test_correction_keeps_user_input_but_discards_late_native_result(tmp_path):
    store, _ = setup(tmp_path)
    old = store.begin("First")
    new = store.begin("Correction")
    assert new["history"] == [{"role": "user", "content": "First"}]
    with pytest.raises(ActionError, match="obsolete"):
        store.finish(old["turn_id"], answer(old, "First", "Late response"))
    assert not store.abort(old["turn_id"])
    assert store.service.get_world()["conversation"]["turn_id"] == new["turn_id"]
    store.finish(new["turn_id"], answer(new, "Correction"))
    assert "Late response" not in json.dumps(store.begin("Third")["history"])


def test_expiry_and_provider_failure_never_commit_model_history(tmp_path):
    store, now = setup(tmp_path)
    old = store.begin("Timed out", timeout=1)
    now[0] += 1
    with pytest.raises(ActionError, match="expired"):
        store.finish(old["turn_id"], answer(old, "Timed out"))
    assert store.abort(old["turn_id"])
    new = store.begin("Retry")
    bad = answer(new, "Retry", "Provider error")
    bad["failed"] = True
    with pytest.raises(ValueError, match="successful"):
        store.finish(new["turn_id"], bad)
    store.abort(new["turn_id"])
    history = store.begin("Correction")["history"]
    assert history == [
        {"role": "user", "content": "Timed out"},
        {"role": "user", "content": "Retry"},
    ]


@pytest.mark.parametrize("operation", ["begin", "finish"])
def test_world_and_history_rollback_together(tmp_path, operation):
    store, _ = setup(tmp_path)
    turn = store.begin("Initial")
    with store.service.runtime.connection() as conn:
        conn.execute("""CREATE TRIGGER fail_turn BEFORE UPDATE ON world
            BEGIN SELECT RAISE(ABORT, 'atomic turn failure'); END;""")
        before = list(conn.iterdump())
    with pytest.raises(sqlite3.IntegrityError, match="atomic turn failure"):
        if operation == "begin":
            store.begin("Correction")
        else:
            store.finish(turn["turn_id"], answer(turn, "Initial"))
    with store.service.runtime.connection() as conn:
        assert list(conn.iterdump()) == before


def test_history_limit_rejects_without_erasing_or_truncating(tmp_path):
    store, _ = setup(tmp_path)
    turn = store.begin("Input")
    result = answer(turn, "Input", "x" * 524288)
    with pytest.raises(ValueError, match="limit"):
        store.finish(turn["turn_id"], result)
    assert store.service.get_world()["conversation"]["turn_id"] == turn["turn_id"]
    assert store.begin("Correction")["history"] == [{"role": "user", "content": "Input"}]


def test_fixture_cannot_be_used_as_conversation_history(tmp_path):
    with pytest.raises(ActionError, match="session"):
        ConversationStore(ExecutionService(Runtime(tmp_path / "fixture.sqlite3")))


def test_mismatched_or_missing_input_cannot_replace_history(tmp_path):
    store, _ = setup(tmp_path)
    turn = store.begin("Preserve this input")
    result = answer(turn, "Different input")
    with pytest.raises(ValueError, match="retain"):
        store.finish(turn["turn_id"], result)
    result["messages"] = [{"role": "assistant", "content": "Response"}]
    with pytest.raises(ValueError, match="retain"):
        store.finish(turn["turn_id"], result)
    assert store.service.get_world()["conversation"]["turn_id"] == turn["turn_id"]
    store.finish(turn["turn_id"], answer(turn, "Preserve this input"))


def test_native_hermes_merge_of_unanswered_user_tail_is_preserved(tmp_path):
    store, _ = setup(tmp_path)
    store.begin("Unanswered")
    turn = store.begin("Correction")
    result = answer(turn, "Correction")
    result["messages"] = [
        {"role": "user", "content": "Unanswered\n\nCorrection"},
        {"role": "assistant", "content": "Response"},
    ]
    store.finish(turn["turn_id"], result)
    assert store.begin("Next")["history"] == result["messages"]


@pytest.mark.parametrize("fail", [False, True])
def test_v5_migration_has_empty_history_and_preserves_backup(tmp_path, fail):
    store, _ = setup(tmp_path)
    store.service.begin_turn()
    path = store.service.runtime.path
    with store.service.runtime.connection() as conn:
        world = read_world(conn)
        world["schema_version"] = 5
        conn.execute("UPDATE world SET data=? WHERE id=1", (json.dumps(world),))
        conn.execute("DROP TABLE conversation_turns")
        conn.execute("DROP TABLE memory_notes")
        if fail:
            conn.execute("""CREATE TRIGGER fail_v6 BEFORE UPDATE ON world
                BEGIN SELECT RAISE(ABORT, 'v6 rollback'); END;""")
        before = list(conn.iterdump())
    backup = tmp_path / "v5-backup.sqlite3"
    if fail:
        with pytest.raises(sqlite3.IntegrityError, match="v6 rollback"):
            migrate(path, backup)
        with sqlite3.connect(path) as conn:
            assert list(conn.iterdump()) == before
    else:
        migrate(path, backup)
        with sqlite3.connect(path) as conn:
            state = read_world(conn)
            assert state["conversation"] is None
            assert state["pose"] == world["pose"]
            assert conn.execute("SELECT COUNT(*) FROM conversation_turns").fetchone()[0] == 0
    with sqlite3.connect(backup) as conn:
        assert list(conn.iterdump()) == before
