import json

import pytest

from promethee.conversation import ConversationStore
from promethee.execution import ExecutionService
from promethee.live_startup import build_startup
from promethee.live_worker import startup
from promethee.runtime import Runtime


def store_at(path):
    return ConversationStore(ExecutionService(Runtime(path, data_origin="session")))


def view(config):
    return json.loads(config["input"][0]["content"][0]["text"].split("\n", 1)[1])


def test_fresh_frontend_has_no_scripted_history_and_roundtrips(tmp_path):
    store = store_at(tmp_path / "world.sqlite3")
    before = store.service.runtime.snapshot()
    config = build_startup(store)
    context = view(config)
    assert context["messages"] == []
    assert context["history_available_in_backend"] is False
    assert context["world_id"] == before["world_id"]
    assert context["heard_by_user"] is None
    assert "coffre" not in config["instructions"]
    assert "coffre" in build_startup(store, memory_enabled=True)["instructions"]
    assert store.service.runtime.snapshot() == before
    path = tmp_path / "startup.json"
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    assert startup(path) == config


def test_restart_reuses_native_dialogue_without_presenting_tool_details_as_speech(tmp_path):
    path = tmp_path / "world.sqlite3"
    store = store_at(path)
    opened = store.begin("Où en sommes-nous ?")
    store.finish(
        opened["turn_id"],
        {
            "type": "result",
            "turn_id": opened["turn_id"],
            "failed": False,
            "interrupted": False,
            "text": "La vérification est en attente.",
            "messages": [
                {"role": "user", "content": "Où en sommes-nous ?"},
                {"role": "tool", "content": "Synthetic internal tool detail"},
                {"role": "assistant", "content": "La vérification est en attente."},
            ],
        },
    )
    reopened = store_at(path)
    context = view(build_startup(reopened))
    assert [m["role"] for m in context["messages"]] == ["user", "assistant"]
    assert context["tool_details_included"] is False
    assert context["heard_by_user"] is None
    assert len(reopened.context()["messages"]) == 3


def test_large_history_remains_in_hermes_without_a_fabricated_summary(tmp_path):
    store = store_at(tmp_path / "world.sqlite3")
    store.begin("Un message long : " + "é" * 8000)
    original = store.context()
    context = view(build_startup(store))
    assert context["history_included"] is False
    assert context["history_available_in_backend"] is True
    assert context["messages"] == []
    assert context["reason"] == "consult_hermes_for_history"
    assert store.context() == original


@pytest.mark.parametrize("change", ["role", "extra", "oversized"])
def test_invalid_startup_file_is_rejected_before_a_connection(tmp_path, change):
    config = build_startup(store_at(tmp_path / "world.sqlite3"))
    if change == "role":
        config["input"][0]["role"] = "tool"
    elif change == "extra":
        config["api_key"] = "must-not-be-accepted"
    else:
        config["input"][0]["content"][0]["text"] = "x" * 8000
    path = tmp_path / "startup.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError):
        startup(path)
