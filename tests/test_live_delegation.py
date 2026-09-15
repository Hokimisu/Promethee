import json

import pytest

from promethee.chat import TextHost
from promethee.conversation import ConversationStore
from promethee.execution import ExecutionService
from promethee.live_delegation import LiveDelegation
from promethee.runtime import Runtime


class Worker:
    def __init__(self, request, store):
        self.request, self.store = request, store
        self.ready, self.closed = False, False
        self.text = "Le monde ne confirme aucune action."

    def poll(self):
        if not self.ready:
            return None
        request = self.request
        return {
            "type": "result",
            "turn_id": request["turn_id"],
            "failed": False,
            "interrupted": False,
            "text": self.text,
            "messages": [
                *request["history"],
                {"role": "user", "content": request["message"]},
                {"role": "assistant", "content": self.text},
            ],
        }

    def close(self):
        self.closed = True


def make_bridge(tmp_path, budget=2):
    store = ConversationStore(
        ExecutionService(Runtime(tmp_path / "world.sqlite3", data_origin="session"))
    )
    workers = []

    def factory(request):
        worker = Worker(request, store)
        workers.append(worker)
        return worker

    host = TextHost(store, factory, model="fixture", base_url="unused", api_mode="chat_completions")
    now = [0.0]
    bridge = LiveDelegation(host, call_budget=budget, clock=lambda: now[0])
    bridge.accept({"type": "session.started", "session": {"id": "live-fixture"}})
    return bridge, workers, now, store


def fragment(text, identifier="input-1", *, output=False):
    return {
        "type": f"session.{'output' if output else 'input'}_transcript.delta",
        "event_id": identifier,
        "start_ms": 0,
        "end_ms": 100,
        "delta": text,
    }


def delegation(identifier="delegation-1", item="item_opaque"):
    return {
        "type": "session.delegation.created",
        "event_id": identifier,
        "offset_ms": 75,
        "delegation": {"id": item, "type": "delegation", "target": "client"},
    }


def test_fragments_around_delegation_keep_provenance_and_exact_id(tmp_path):
    bridge, workers, now, store = make_bridge(tmp_path)
    bridge.accept(fragment("Lis "))
    bridge.accept(dict(reversed(list(fragment("Lis ").items()))))
    bridge.accept(delegation())
    assert bridge.poll() == [] and not workers
    bridge.accept(fragment("le monde.", "input-2"))
    bridge.accept(fragment("Je regarde.", "output-1", output=True))
    now[0] = 0.21
    assert bridge.poll() == []
    assert len(workers) == 1
    request = workers[0].request
    context = json.loads(request["message"].split("Données de contexte :\n")[1])
    assert context["utterance_complete"] is False
    assert context["heard_by_user"] is None
    assert [f["source"] for f in context["fragments_in_arrival_order"]] == [
        "user_transcript",
        "user_transcript",
        "live_output_transcript",
    ]
    workers[0].ready = True
    result = bridge.poll()[0]
    assert result["event"]["delegation_id"] == "item_opaque"
    assert result["status"] == "completed"
    with store.service.runtime.connection() as conn:
        record = json.loads(conn.execute("SELECT data FROM conversation_turns").fetchone()[0])
        assert record["trigger"] == "live"
        assert record["speech_delivery"] is None
    bridge.accept(delegation("duplicate-new-event"))
    assert bridge.poll() == [] and len(workers) == 1


def test_late_fragment_fences_tools_before_cleanup_and_drops_old_result(tmp_path):
    bridge, workers, now, store = make_bridge(tmp_path)
    bridge.accept(fragment("Déplace-toi"))
    bridge.accept(delegation())
    now[0] = 1
    bridge.poll()

    def fenced_close():
        assert store.service.get_world()["conversation"] is None
        workers[0].closed = True

    workers[0].close = fenced_close
    workers[0].ready = True
    bridge.accept(fragment(" non, attends.", "correction"))
    result = bridge.poll()[0]
    assert result["status"] == "interrupted"
    assert result["code"] == "new_input_fragment"
    assert workers[0].closed
    assert bridge.poll() == [] and len(workers) == 1
    with store.service.runtime.connection() as conn:
        assert conn.execute("SELECT status FROM conversation_turns").fetchone()[0] == "interrupted"


def test_changed_duplicate_fails_closed(tmp_path):
    bridge, workers, now, store = make_bridge(tmp_path)
    bridge.accept(fragment("Lis"))
    bridge.accept(delegation())
    now[0] = 1
    bridge.poll()
    with pytest.raises(ValueError, match="reused"):
        bridge.accept(fragment("Agis"))
    assert workers[0].closed and store.service.get_world()["conversation"] is None


def test_call_budget_and_long_result_are_explicit(tmp_path):
    bridge, workers, now, _ = make_bridge(tmp_path, budget=1)
    bridge.accept(fragment("Explique"))
    bridge.accept(delegation())
    now[0] = 1
    bridge.poll()
    workers[0].text, workers[0].ready = "é" * 300, True
    result = bridge.poll()[0]
    assert result["text"] == "é" * 300
    assert len(result["event"]["content"].encode()) <= 500
    assert "dépasse" in result["event"]["content"]
    with pytest.raises(ValueError, match="budget"):
        bridge.accept(delegation("new", "other_opaque"))
    assert len(workers) == 1


def test_transport_error_drops_pending_output_and_does_not_replay(tmp_path):
    bridge, workers, now, store = make_bridge(tmp_path)
    bridge.accept(fragment("Bonjour"))
    bridge.accept(delegation())
    now[0] = 1
    bridge.poll()
    workers[0].ready = True
    bridge.accept({"type": "transport.error", "code": "fixture_failure"})
    assert bridge.poll() == []
    assert store.service.get_world()["conversation"] is None
    assert workers[0].closed


def test_startup_delegation_without_fresh_user_input_does_not_resume_old_work(tmp_path):
    bridge, workers, now, _ = make_bridge(tmp_path)
    bridge.accept(delegation())
    now[0] = 1
    assert bridge.poll() == []
    assert not workers and bridge.remaining == 2
    bridge.accept(fragment("Quelle est la situation actuelle ?"))
    now[0] = 1.21
    assert bridge.poll() == []
    assert len(workers) == 1 and bridge.remaining == 1


@pytest.mark.parametrize("fail", [False, True])
def test_audio_is_cleared_before_backend_cleanup_even_on_audio_failure(tmp_path, fail):
    bridge, workers, now, store = make_bridge(tmp_path)
    bridge.accept(fragment("Bonjour"))
    bridge.accept(delegation())
    now[0] = 1
    bridge.poll()
    order = []

    def clear():
        order.append("audio")
        if fail:
            raise ValueError("device failure")

    def cleanup():
        assert order[0] == "audio"
        assert store.service.get_world()["conversation"] is None
        order.append("backend")

    bridge.before_invalidate = clear
    workers[0].close = cleanup
    if fail:
        with pytest.raises(ValueError, match="device failure"):
            bridge.close()
    else:
        bridge.close()
    assert order == ["audio", "backend"]
    assert bridge.pending is None and bridge.turn_id is None
