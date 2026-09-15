import json

import pytest

from promethee.conversation import ConversationStore
from promethee.execution import ExecutionService
from promethee.live_startup import build_startup
from promethee.runtime import Runtime


def open_store(path):
    return ConversationStore(ExecutionService(Runtime(path, data_origin="session")))


def fragment(text, output=False):
    return {
        "source": "live_output_transcript" if output else "user_transcript",
        "start_ms": 0,
        "end_ms": 100,
        "text": text,
    }


def test_restart_keeps_nondelegated_fragments_without_creating_work(tmp_path):
    path = tmp_path / "world.sqlite3"
    store = open_store(path)
    before = store.service.runtime.snapshot()
    store.record_live_fragment("session", "event1", fragment("Bonjour"))
    store.record_live_fragment("session", "event2", fragment("Salut", True))
    store.record_live_fragment("session", "event1", fragment("Bonjour"))
    assert store.service.runtime.snapshot() == before
    reopened = open_store(path)
    reopened.recover()
    history = reopened.context()["messages"]
    assert len(history) == 2
    for message in history:
        payload = json.loads(message["content"].split("\n", 1)[1])
        assert payload["utterance_complete"] is False and payload["heard_by_user"] is None
    assert "live_output_transcript" in history[1]["content"]
    config = build_startup(reopened)
    assert "Bonjour" in config["input"][0]["content"][0]["text"]
    assert reopened.service.get_world()["conversation"] is None
    with reopened.service.runtime.connection() as conn:
        assert conn.execute("SELECT count(*) FROM executions").fetchone()[0] == 0
        assert conn.execute("SELECT DISTINCT status FROM conversation_turns").fetchall() == [
            ("context",)
        ]


def test_duplicate_with_changed_content_rolls_back(tmp_path):
    store = open_store(tmp_path / "world.sqlite3")
    store.record_live_fragment("s", "e", fragment("Bonjour"))
    before = store.context()
    with pytest.raises(ValueError, match="reused"):
        store.record_live_fragment("s", "e", fragment("Autre"))
    assert store.context() == before


def test_late_output_context_survives_native_compaction_and_merged_user_tail(tmp_path):
    store = open_store(tmp_path / "world.sqlite3")
    store.record_live_fragment("s", "e1", fragment("Début"))
    opened = store.begin("Question", trigger="live")
    known = [*opened["history"], {"role": "user", "content": "Question"}]
    merged = "\n\n".join(message["content"] for message in known)
    store.record_live_fragment("s", "e2", fragment("Une sortie tardive", True))
    store.finish(
        opened["turn_id"],
        {
            "type": "result",
            "turn_id": opened["turn_id"],
            "failed": False,
            "interrupted": False,
            "text": "Réponse",
            "messages": [
                {"role": "user", "content": merged},
                {"role": "assistant", "content": "Réponse"},
            ],
        },
    )
    history = store.context()["messages"]
    assert len(history) == 3
    assert "Une sortie tardive" in history[-1]["content"]
    next_turn = store.begin("Suite")
    assert next_turn["history"] == history


def test_context_limit_fails_atomically(tmp_path, monkeypatch):
    store = open_store(tmp_path / "world.sqlite3")
    monkeypatch.setattr("promethee.conversation.HISTORY_BYTES", 10)
    with pytest.raises(ValueError, match="limit"):
        store.record_live_fragment("s", "e", fragment("Bonjour"))
    assert store.context()["messages"] == []
