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
from promethee.initiative import Initiative
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


@pytest.mark.parametrize("allow_silence", [False, None, 0, 1, "true"])
def test_silence_requires_explicit_boolean_permission(allow_silence):
    with pytest.raises(ValueError):
        parse_delivery('{"silent": true}', allow_silence=allow_silence)
    with pytest.raises(ValueError):
        parse_delivery('{"silent": true}')


@pytest.mark.parametrize(
    "value",
    [
        {"silent": False},
        {"silent": 1},
        {"silent": 0},
        {"silent": None},
        {"silent": "true"},
        {"silent": []},
        {"silent": True, "text": ""},
        {"silent": True, "delivery": "quiet"},
        {"silent": True, "reason": "Nothing to add."},
        {"silent": True, "text": "Bonjour", "delivery": "warm"},
    ],
)
def test_silent_choice_requires_exact_keys_and_true_boolean(value):
    raw = json.dumps(value)
    with pytest.raises(ValueError):
        parse_delivery(raw, allow_silence=True)
    native = Mock()
    native.poll.return_value = {"type": "result", "turn_id": "turn", "text": raw}
    directions = {}
    worker = DirectedWorker(native, "turn", directions, allow_silence=True)
    assert worker.poll() == {"type": "error", "code": "invalid_vocal_direction"}
    assert directions == {}


def test_silent_result_and_native_history_are_returned_verbatim(monkeypatch):
    def unexpected_speech(*args, **kwargs):
        pytest.fail("A silent choice must never prepare spoken words.")

    monkeypatch.setattr("delivery.prepare_speech_text", unexpected_speech)
    raw_text = ' {"silent": true} '
    assert parse_delivery(raw_text, allow_silence=True) is None
    result = {
        "type": "result",
        "turn_id": "turn",
        "text": raw_text,
        "messages": [{"role": "assistant", "content": raw_text}],
        "timing": {"conversation_seconds": 1.25},
    }
    native = Mock()
    native.poll.return_value = result
    directions = {}
    assert DirectedWorker(native, "turn", directions, allow_silence=True).poll() is result
    assert directions == {"turn": None}


def test_silence_permission_keeps_the_spoken_response_api():
    payload = {"text": "Je peux aussi répondre.", "delivery": "Warm and thoughtful."}
    assert parse_delivery(json.dumps(payload), allow_silence=True) == payload


def test_initiative_silence_persists_native_history_but_user_reply_cannot_use_it(tmp_path):
    runtime = Runtime(
        tmp_path / "world.sqlite3", data_origin="session", session_kind="qualification"
    )
    now = [100.0]
    store = ConversationStore(ExecutionService(runtime, clock=lambda: now[0]))
    directions = {}
    requests = []
    native_content = '{"silent": true}'

    def factory(request):
        requests.append(request)
        native = Mock()
        native.poll.return_value = {
            "type": "result",
            "turn_id": request["turn_id"],
            "failed": False,
            "interrupted": False,
            "text": native_content,
            "messages": [
                *request["history"],
                {"role": "user", "content": request["message"]},
                {"role": "assistant", "content": native_content},
            ],
        }
        return native

    host = TextHost(store, factory, model="test", base_url="local", api_mode="chat_completions")
    host.worker_wrapper = lambda worker, request: DirectedWorker(
        worker,
        request["turn_id"],
        directions,
        allow_silence=host.initiative_turn == request["turn_id"],
    )
    initiative = Initiative(store.service)
    initiative.configure(budget=1, interval=1)
    now[0] += 1
    turn = host.initiative_tick()["started"]
    assert host.poll() == {"status": "completed", "text": native_content}
    assert directions == {turn: None}
    with runtime.connection() as conn:
        row = conn.execute(
            "SELECT status,data FROM conversation_turns WHERE turn_id=?", (turn,)
        ).fetchone()
    record = json.loads(row[1])
    assert row[0] == "completed"
    assert record["trigger"] == "initiative"
    assert record["text"] == native_content
    assert record["messages"][-1] == {"role": "assistant", "content": native_content}
    assert record["speech_delivery"] is None
    assert initiative.observe()["remaining"] == 0

    # Even copying a runtime wake into user text does not grant silence permission.
    user_turn = host.start(requests[0]["message"])
    assert host.initiative_turn is None
    assert requests[-1]["history"][-1] == {"role": "assistant", "content": native_content}
    assert host.poll() == {"status": "failed", "code": "model_or_worker_failure"}
    assert user_turn not in directions
    host.close()


def test_late_silent_result_is_rejected_by_host_without_publishing_a_direction(tmp_path):
    runtime = Runtime(
        tmp_path / "world.sqlite3", data_origin="session", session_kind="qualification"
    )
    store = ConversationStore(ExecutionService(runtime))
    directions = {}

    def factory(request):
        native = Mock()
        native.poll.return_value = {
            "type": "result",
            "turn_id": "another-turn",
            "text": '{"silent": true}',
            "failed": False,
            "interrupted": False,
            "messages": [
                {"role": "user", "content": request["message"]},
                {"role": "assistant", "content": '{"silent": true}'},
            ],
        }
        return DirectedWorker(native, request["turn_id"], directions, allow_silence=True)

    host = TextHost(store, factory, model="test", base_url="local", api_mode="chat_completions")
    host.start("Réveille-toi.")
    assert host.poll() == {"status": "failed", "code": "model_or_worker_failure"}
    assert directions == {}
    host.close()
