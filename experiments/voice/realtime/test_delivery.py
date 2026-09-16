"""CPU tests with a mocked Hermes worker; no model or voice qualification."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from delivery import DirectedWorker, parse_delivery
from dialogue import ROOT, instructions

from promethee.chat import TextHost
from promethee.conversation import ConversationStore
from promethee.execution import ExecutionService
from promethee.runtime import Runtime


def test_character_instructions_resolve_from_clone_not_working_directory(monkeypatch, tmp_path):
    expected_root = Path(__file__).resolve().parents[3]
    assert ROOT == expected_root
    identity = (expected_root / "docs/characters/ariane.md").read_text(encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert instructions().startswith(identity + "\n")


@pytest.mark.parametrize(
    "raw",
    [
        "texte sans objet JSON",
        "[]",
        "{}",
        '{"text":"Bonjour","delivery":""}',
        '{"text":"Bonjour","delivery":"warm","extra":true}',
        json.dumps({"text": "a" * 701, "delivery": "warm"}),
        json.dumps({"text": "bonjour", "delivery": "a" * 301}),
        json.dumps({"text": ["bonjour"], "delivery": "warm"}),
        json.dumps({"text": "Bonjour " * 25, "delivery": "warm"}),
        json.dumps({"text": "[sigh] Ah, [laughing] tu es là.", "delivery": "amused"}),
        json.dumps({"text": "(en riant) Bonjour.", "delivery": "amused"}),
        json.dumps({"text": "[pause:1s] Bonjour.", "delivery": "warm"}),
    ],
)
def test_invalid_direction_is_not_spoken(raw):
    with pytest.raises(ValueError):
        parse_delivery(raw)
    native = Mock()
    native.poll.return_value = {"type": "result", "turn_id": "turn", "text": raw}
    directions = {}
    assert DirectedWorker(native, "turn", directions).poll()["type"] == "error"
    assert directions == {}


def test_actual_spoken_words_persist_without_changing_native_history(tmp_path):
    runtime = Runtime(
        tmp_path / "world.sqlite3", data_origin="session", session_kind="qualification"
    )
    store = ConversationStore(ExecutionService(runtime))
    directions = {}
    payload = {"text": "Ça me fait plaisir.", "delivery": "Quiet relief, warm and smiling."}
    native_content = json.dumps(payload)

    def factory(request):
        native = Mock()
        native.poll.return_value = {
            "type": "result",
            "turn_id": request["turn_id"],
            "failed": False,
            "interrupted": False,
            "text": native_content,
            "messages": [
                {"role": "user", "content": request["message"]},
                {"role": "assistant", "content": native_content},
            ],
            "timing": {"conversation_seconds": 1.25},
        }
        return DirectedWorker(native, request["turn_id"], directions)

    host = TextHost(store, factory, model="test", base_url="local", api_mode="chat_completions")
    turn = host.start("Une bonne nouvelle.")
    result = host.poll()
    assert result["text"] == payload["text"]
    assert directions.pop(turn) == payload["delivery"]
    with runtime.connection() as conn:
        record = json.loads(conn.execute("SELECT data FROM conversation_turns").fetchone()[0])
    assert record["text"] == payload["text"]
    assert record["messages"][-1]["content"] == native_content
    assert record["speech_delivery"] is None  # Generating text is not playback.
    host.close()


def test_late_result_does_not_publish_another_turns_direction():
    native = Mock()
    raw = {
        "type": "result",
        "turn_id": "other",
        "text": json.dumps({"text": "Bonjour", "delivery": "warm"}),
    }
    native.poll.return_value = raw
    directions = {}
    assert DirectedWorker(native, "current", directions).poll() is raw
    assert not directions


def test_supported_tag_does_not_count_as_spoken_words():
    payload = {"text": "[sigh] " + "bonjour " * 24, "delivery": "Patient (gentle), then amused."}
    result = parse_delivery(json.dumps(payload))
    assert result["text"].startswith("[sigh]")
    assert result["delivery"] == "Patient gentle, then amused."
