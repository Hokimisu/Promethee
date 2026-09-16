"""Session initiative contracts with real durable stores, no models or subprocesses."""

import collections
import copy
import hashlib
import json
import queue
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import body as body_module
import pytest
from delivery import DirectedWorker
from test_serve import server

from promethee.chat import TextHost
from promethee.conversation import ConversationStore
from promethee.execution import ExecutionService
from promethee.initiative import Initiative
from promethee.runtime import Runtime
from promethee.world import ActionError


class CPUWorker:
    def __init__(self, request):
        self.request = copy.deepcopy(request)
        self.results = collections.deque()
        self.closed = False

    def finish(self, content='{"silent": true}'):
        request = self.request
        self.results.append(
            {
                "type": "result",
                "turn_id": request["turn_id"],
                "failed": False,
                "interrupted": False,
                "text": content,
                "messages": [
                    *request["history"],
                    {"role": "user", "content": request["message"]},
                    {"role": "assistant", "content": content},
                ],
            }
        )

    def poll(self):
        return self.results.popleft() if self.results else None

    def close(self):
        self.closed = True


@pytest.fixture
def session(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(server.time, "monotonic", lambda: now[0])
    item = server.Session.__new__(server.Session)
    item.lock = threading.RLock()
    item.commands = queue.Queue(maxsize=16)
    item.vox_events = queue.Queue()
    item.events = collections.deque(maxlen=640)
    item.cursor = 0
    item.sid = item.active_sid = "cpu-session"
    item.state = {"session_id": item.sid, "phase": "idle", "text": ""}
    item.vox_ready = True
    item.asr = None
    item.asr_status = {"state": "disabled", "error": None}
    item.input_capture = None
    item.input_ids = set()
    item.pending_audio = item.pending_text = item.speech = None
    item.running = False
    item.auto_continue = False
    item.began = None
    item.calls = 0
    item.turn_id = item.turn_source = None
    item.output_deadline = 0.0
    item.brain_started = 0.0
    item.next_brain_warm = 0.0
    item.next_metrics_write = float("inf")
    item.stopping = threading.Event()
    item.output = tmp_path
    item.deliveries = {}
    item.metric = {"brain_seconds": [], "brain_timings": [], "voice_runs": []}
    service = ExecutionService(
        Runtime(tmp_path / "world.sqlite3", data_origin="session", session_kind="qualification"),
        clock=lambda: now[0],
    )
    item.body = Mock()
    item.body.service = service
    item.body.poll.side_effect = lambda: {
        "ready": item.body_ready,
        "world": service.get_world(),
    }
    item.body_ready = True
    item.initiative = Initiative(service)
    workers = []

    def factory(request):
        worker = CPUWorker(request)
        workers.append(worker)
        return worker

    item.host = TextHost(
        ConversationStore(service),
        factory,
        model="cpu-test",
        base_url=None,
        api_mode="chat_completions",
    )
    item.host.worker_wrapper = lambda worker, request: DirectedWorker(
        worker,
        request["turn_id"],
        item.deliveries,
        allow_silence=item.host.initiative_turn == request["turn_id"],
    )
    item.host.initiative_tick = Mock(wraps=item.host.initiative_tick)
    item.vox_send = Mock()
    item.think = Mock(wraps=item.think)
    item.cpu_clock, item.cpu_workers = now, workers
    yield item
    item.host.close()


def one_iteration(item, monkeypatch):
    """Run the real owner loop once; no sleeping, background thread or socket."""
    item.stopping.clear()
    with monkeypatch.context() as local:
        local.setattr(server.time, "sleep", lambda _: item.stopping.set())
        item.loop()


def configure(item, *, budget=2, interval=1):
    return item.post("initiative_configure", {"budget": budget, "interval": interval})


def start_wake(item):
    configure(item)
    item.cpu_clock[0] += 1
    item._poll_initiative()
    assert len(item.cpu_workers) == 1
    return item.turn_id


def persisted(item):
    return item.body.service.runtime.snapshot()["initiative"]


def turn_record(item, turn):
    with item.body.service.runtime.connection() as conn:
        row = conn.execute(
            "SELECT status,data FROM conversation_turns WHERE turn_id=?", (turn,)
        ).fetchone()
    return row[0], json.loads(row[1])


def test_default_is_disabled_and_initial_snapshot_has_no_implicit_budget(session):
    item = session
    assert item.snapshot()["initiative"] is None
    assert item.snapshot()["turn_source"] is None
    item._poll_initiative()
    assert persisted(item) is None and not item.cpu_workers


def test_configuration_is_explicit_once_and_initializes_only_ui_fence(session):
    item = session
    item.sid = item.active_sid = ""
    result = configure(item, budget=3, interval=4)
    assert result["session_id"] == item.sid == item.active_sid
    assert item.sid
    assert result["cursor"] == item.cursor
    assert result["interrupted"] is False
    assert result["initiative"] == persisted(item)
    assert persisted(item)["remaining"] == 3 and persisted(item)["used"] == 0
    assert item.output_deadline == item.cpu_clock[0] + 15
    assert item.snapshot()["initiative"] == persisted(item)
    before = copy.deepcopy(persisted(item))
    with pytest.raises(ActionError, match="already configured"):
        configure(item, budget=7)
    assert persisted(item) == before
    assert not item.cpu_workers


def test_real_budget_cadence_silence_and_exhaustion(session, monkeypatch):
    item = session
    configure(item, budget=2, interval=1)
    item._poll_initiative()
    assert not item.cpu_workers
    for expected_used in (1, 2):
        item.cpu_clock[0] += 1
        item._poll_initiative()
        assert len(item.cpu_workers) == expected_used
        turn = item.turn_id
        assert item.turn_source == "initiative"
        assert item.snapshot()["turn_source"] == "initiative"
        assert item.brain_started == item.cpu_clock[0]
        assert item.host.turn_id == turn
        assert persisted(item)["used"] == expected_used
        assert persisted(item)["remaining"] == 2 - expected_used
        item.think.assert_not_called()
        item.cpu_workers[-1].finish()
        one_iteration(item, monkeypatch)
        status, record = turn_record(item, turn)
        assert status == "completed" and record["trigger"] == "initiative"
        assert record["text"] == '{"silent": true}'
        assert record["speech_delivery"] is None
        assert item.state["phase"] == "idle"
        assert item.pending_text is None and item.speech is None
        item.vox_send.assert_not_called()
    item.cpu_clock[0] += 2
    item._poll_initiative()
    assert len(item.cpu_workers) == 2


@pytest.mark.parametrize(
    "gate",
    [
        "voice_loading",
        "body_loading",
        "capture",
        "transcribing",
        "asr_busy",
        "pending_audio",
        "speech",
        "pending_text",
        "worker",
        "pending_result",
        "stale_sid",
        "no_sid",
        "output_expired",
        "output_never_enabled",
    ],
)
def test_busy_or_unavailable_output_never_spends_budget(session, gate):
    item = session
    configure(item)
    item.cpu_clock[0] += 1
    if gate == "voice_loading":
        item.vox_ready = False
    elif gate == "body_loading":
        item.body_ready = False
    elif gate in {"capture", "transcribing"}:
        item.input_capture = {"state": "listening" if gate == "capture" else "transcribing"}
    elif gate == "asr_busy":
        item.asr = SimpleNamespace(busy=True)
    elif gate == "pending_audio":
        item.pending_audio = {"session_id": item.sid}
    elif gate == "speech":
        item.speech = {"id": "speech", "terminal": False}
    elif gate == "pending_text":
        item.pending_text = {"id": "text"}
    elif gate == "worker":
        item.host.worker = Mock()
    elif gate == "pending_result":
        item.host.pending_result = {"status": "failed"}
    elif gate == "stale_sid":
        item.active_sid = "obsolete-session"
    elif gate == "no_sid":
        item.sid = item.active_sid = ""
    elif gate == "output_expired":
        item.output_deadline = item.cpu_clock[0]
    elif gate == "output_never_enabled":
        item.output_deadline = 0.0
    item._poll_initiative()
    assert not item.cpu_workers
    assert persisted(item)["used"] == 0 and persisted(item)["remaining"] == 2


def test_world_events_are_coalesced_while_busy_and_used_once_when_ready(session):
    item = session
    configure(item, budget=2, interval=None)
    item.input_capture = {"state": "listening"}
    for index in range(12):
        service = item.body.service
        result = service.submit(
            f"rejected-{index}",
            service.get_world()["revision"],
            {"kind": "move", "args": {"position": [0.5, 0.0]}},
        )
        assert result["status"] == "rejected"
    item._poll_initiative()
    state = persisted(item)
    assert state["pending"]["terminal_count"] == 12
    assert len(state["pending"]["latest"]) == 8
    assert state["used"] == 0 and not item.cpu_workers
    item._poll_initiative()
    assert persisted(item)["pending"] == state["pending"]
    item.input_capture = None
    item._poll_initiative()
    assert len(item.cpu_workers) == 1 and persisted(item)["used"] == 1
    assert '"terminal_count": 12' in item.cpu_workers[0].request["message"]
    assert persisted(item)["pending"]["terminal_count"] == 0


def test_pause_aborts_active_initiative_durably_before_ack_and_fences_late_tools(session):
    item = session
    turn = start_wake(item)
    previous_sid = item.sid
    result = item.post("initiative_pause", {"paused": True})
    assert result["interrupted"] is True
    assert result["session_id"] == item.sid != previous_sid
    assert persisted(item)["paused"] is True
    assert persisted(item)["used"] == 1 and persisted(item)["remaining"] == 1
    assert persisted(item)["active_turn"] is None
    assert turn_record(item, turn)[0] == "interrupted"
    assert item.body.service.runtime.snapshot()["conversation"] is None
    service = item.body.service
    with pytest.raises(ActionError):
        service.submit(
            "obsolete-tool",
            service.get_world()["revision"],
            {"kind": "move", "args": {"position": [0.5, 0.0]}},
            turn_id=turn,
        )
    item.body.cancel.assert_not_called()


def test_pause_user_turn_preserves_its_authority_fence_and_body(session):
    item = session
    configure(item)
    item.think("Un message utilisateur.")
    item.running = True
    turn, sid, worker = item.turn_id, item.sid, item.cpu_workers[-1]
    assert item.turn_source == "user"
    result = item.post("initiative_pause", {"paused": True})
    assert result["interrupted"] is False and item.sid == sid
    assert turn_record(item, turn)[0] == "running"
    assert item.body.service.runtime.snapshot()["conversation"]["turn_id"] == turn
    assert not worker.closed
    item.body.cancel.assert_not_called()
    item.vox_send.assert_not_called()


@pytest.mark.parametrize("phase", ["idle", "finished_speech"])
def test_pause_without_outstanding_autonomous_output_keeps_sid(session, phase):
    item = session
    configure(item)
    item.turn_source = "initiative" if phase == "finished_speech" else None
    if phase == "finished_speech":
        item.speech = {"id": "ended", "done": True, "terminal": True}
    sid = item.sid
    result = item.post("initiative_pause", {"paused": True})
    assert result["interrupted"] is False and item.sid == sid
    assert persisted(item)["paused"] is True
    item.body.cancel.assert_not_called()


def test_pause_survives_new_host_and_explicit_resume_keeps_consumed_budget(session):
    item = session
    start_wake(item)
    item.post("initiative_pause", {"paused": True})
    before = copy.deepcopy(persisted(item))
    item.host.close()
    runtime = Runtime(
        item.body.service.runtime.path,
        data_origin="session",
        session_kind="qualification",
        create=False,
    )
    service = ExecutionService(runtime, clock=lambda: item.cpu_clock[0])
    item.body.service = service
    item.initiative = Initiative(service)
    item.host = TextHost(
        ConversationStore(service),
        Mock(side_effect=AssertionError("No wake before resume")),
        model="cpu-test",
        base_url=None,
        api_mode="chat_completions",
    )
    assert persisted(item) == before
    item.sid = item.active_sid = ""
    item.output_deadline = 0
    result = item.post("initiative_pause", {"paused": False})
    assert result["initiative"]["paused"] is False
    assert result["initiative"]["used"] == 1 and result["initiative"]["remaining"] == 1
    assert result["session_id"] == item.sid == item.active_sid
    assert item.sid and item.output_deadline == item.cpu_clock[0] + 15


def test_input_start_fences_output_without_pausing_persisted_initiative(session):
    item = session
    configure(item)
    item.asr = SimpleNamespace(state="ready", error=None, busy=False)
    item.asr_status = {"state": "ready", "error": None}
    before = copy.deepcopy(persisted(item))
    result = item.post("input_start", {"input_id": "input-cpu-initiative"})
    assert result["session_id"] == item.sid
    assert persisted(item) == before
    item.body.cancel.assert_not_called()


def test_stop_persists_pause_before_returning_and_never_resets_budget(session):
    item = session
    configure(item)
    result = item.post("stop", {})
    assert result["stopped"] is True
    assert persisted(item)["paused"] is True
    assert persisted(item)["remaining"] == 2 and persisted(item)["used"] == 0


@pytest.mark.parametrize("stage", ["worker", "pending_result", "pending_text", "speech"])
def test_pause_cleans_every_outstanding_autonomous_stage_without_body_cancel(
    session, monkeypatch, stage
):
    item = session
    turn = start_wake(item)
    if stage != "worker":
        item.cpu_workers[-1].finish(
            json.dumps({"text": "Je reste ici.", "delivery": "Calm and gentle."})
        )
        completed = item.host.poll()
        assert completed["status"] == "completed"
        if stage == "pending_result":
            item.host.pending_result = completed
        elif stage == "pending_text":
            item.pending_text = {
                "id": "waiting",
                "turn_id": turn,
                "sid": item.sid,
                "text": completed["text"],
                "delivery": item.deliveries[turn],
            }
        else:
            item.speech = {
                "id": "playing",
                "turn_id": turn,
                "sid": item.sid,
                "done": False,
                "terminal": False,
                "first": 100.0,
                "samples": 0,
                "end_estimate": 120.0,
            }
            item.host.store.speech_delivery(turn, "playing", "preparing")
            item.vox_events.put({"event": "pcm", "id": "playing", "samples": 480})
    sid = item.sid
    result = item.post("initiative_pause", {"paused": True})
    assert result["interrupted"] is True and item.sid != sid
    one_iteration(item, monkeypatch)
    assert item.host.worker is None and item.host.pending_result is None
    assert item.pending_text is None and item.speech is None
    assert item.state["phase"] == "idle"
    assert not any(event["event"] == "pcm" for event in item.events)
    assert not any(call.args[0]["op"] == "speak" for call in item.vox_send.call_args_list)
    item.body.cancel.assert_not_called()
    if stage == "speech":
        assert turn_record(item, turn)[1]["speech_delivery"]["status"] == "interrupted"


@pytest.mark.parametrize("pause_origin", ["browser", "durable_external"])
def test_pause_between_native_poll_and_session_publication_never_speaks(
    session, monkeypatch, pause_origin
):
    item = session
    turn = start_wake(item)
    item.cpu_workers[-1].finish(
        json.dumps({"text": "Je peux attendre.", "delivery": "Calm and gentle."})
    )
    native_poll = item.host.poll
    results = []

    def interleaved_poll():
        result = native_poll()
        assert result["status"] == "completed" and item.host.worker is None
        assert item.pending_text is None and item.speech is None
        if pause_origin == "browser":
            results.append(item.post("initiative_pause", {"paused": True}))
        else:
            Initiative(item.body.service).update(paused=True)
        return result

    monkeypatch.setattr(item.host, "poll", interleaved_poll)
    sid = item.sid
    one_iteration(item, monkeypatch)
    item.vox_send.assert_not_called()
    item.body.cancel.assert_not_called()
    assert not any(event["event"] == "speech_start" for event in item.events)
    assert item.pending_text is None and item.speech is None
    status, record = turn_record(item, turn)
    assert status == "completed" and record["speech_delivery"] is None
    assert persisted(item)["paused"] is True
    if pause_origin == "browser":
        assert results[0]["interrupted"] is True and item.sid != sid
    else:
        assert item.sid == sid  # Durable external pause has no authority over the UI fence.


def test_pausing_initiative_does_not_suppress_a_user_reply(session, monkeypatch):
    item = session
    configure(item)
    item.running = True
    item.think("Une réponse, s’il te plaît.")
    turn = item.turn_id
    item.cpu_workers[-1].finish(
        json.dumps({"text": "Oui, je suis là.", "delivery": "Warm and gentle."})
    )
    item.post("initiative_pause", {"paused": True})
    one_iteration(item, monkeypatch)
    assert item.speech["turn_id"] == turn
    assert item.vox_send.call_args.args[0]["op"] == "speak"
    assert persisted(item)["used"] == 0
    item.body.cancel.assert_not_called()


def test_full_queue_refuses_pause_without_partial_durable_or_ui_change(session):
    item = session
    start_wake(item)
    while not item.commands.full():
        item.commands.put_nowait(("telemetry", {}))
    before = copy.deepcopy((item.sid, item.state, persisted(item)))
    with pytest.raises(queue.Full):
        item.post("initiative_pause", {"paused": True})
    assert (item.sid, item.state, persisted(item)) == before
    assert turn_record(item, item.turn_id)[0] == "running"
    assert not item.cpu_workers[-1].closed


@pytest.mark.parametrize("current_sid", [False, True])
def test_only_current_output_heartbeat_renews_expired_wake_lease(session, monkeypatch, current_sid):
    item = session
    configure(item)
    item.cpu_clock[0] += 16
    expired = item.output_deadline
    item.post(
        "telemetry",
        {"event": "client_stats", "session_id": item.sid if current_sid else "obsolete"},
    )
    one_iteration(item, monkeypatch)
    if current_sid:
        assert item.output_deadline == item.cpu_clock[0] + 15
        assert persisted(item)["used"] == 1
    else:
        assert item.output_deadline == expired
        assert persisted(item)["used"] == 0 and not item.cpu_workers


def test_session_constructor_resumes_the_existing_paused_world_without_model_start(
    session, tmp_path, monkeypatch
):
    item = session
    start_wake(item)
    item.post("initiative_pause", {"paused": True})
    item.host.close()
    before = copy.deepcopy(item.body.service.runtime.snapshot())
    avatar = tmp_path / "test-avatar.vrm"
    avatar.write_bytes(b"Synthetic resume test asset")
    monkeypatch.setattr(
        body_module, "PIXIV_SHA256", hashlib.sha256(avatar.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(server, "BodyAdapter", body_module.BodyAdapter)
    thread = Mock()
    monkeypatch.setattr(server.threading, "Thread", Mock(return_value=thread))
    config = {
        "data_dir": tmp_path / "new-logs",
        "resume_world": tmp_path,
        "avatar": avatar,
        "body": {"ardy_python": "unused", "checkpoint_root": "unused"},
        "model": "gpt-5.6-luna",
        "port": 2392,
    }
    resumed = server.Session(config)
    try:
        assert resumed.body.data_dir == tmp_path
        assert resumed.output.parent == config["data_dir"]
        assert resumed.output != item.output
        assert resumed.initiative.service.runtime.snapshot() == before
        assert resumed.output_deadline == 0
        assert resumed.snapshot()["initiative"]["paused"] is True
        assert resumed.snapshot()["initiative"]["used"] == 1
        assert resumed.snapshot()["initiative"]["remaining"] == 1
        thread.start.assert_called_once_with()  # A mock, never a live owner thread.
    finally:
        resumed.body.close()


def test_durable_pause_during_body_presence_activation_prevents_all_voice_publication(
    session, monkeypatch
):
    item = session
    turn = start_wake(item)
    item.cpu_workers[-1].finish(
        json.dumps({"text": "Je peux patienter.", "delivery": "Calm and gentle."})
    )

    def pause_while_body_is_activating(enabled):
        if enabled:
            # Deterministic scheduling point: another trusted caller pauses while
            # set_presence is waiting, before control returns to _speak_current.
            Initiative(item.body.service).update(paused=True)

    item.body.set_presence.side_effect = pause_while_body_is_activating
    one_iteration(item, monkeypatch)
    assert persisted(item)["paused"] is True
    assert any(call.args == (True,) for call in item.body.set_presence.call_args_list)
    assert item.speech is None and item.pending_text is None
    item.vox_send.assert_not_called()
    item.body.cancel.assert_not_called()
    assert not any(event["event"] == "speech_start" for event in item.events)
    status, record = turn_record(item, turn)
    assert status == "completed" and record["speech_delivery"] is None


def test_demo_expiration_is_checked_before_spending_an_initiative_call(session):
    item = session
    configure(item, budget=2, interval=1)
    item.cpu_clock[0] += 1
    item.auto_continue = True
    item.began = item.cpu_clock[0] - 60
    assert item.output_deadline > item.cpu_clock[0]
    assert item.snapshot()["ready"] is True
    before = copy.deepcopy(persisted(item))
    item._poll_initiative()
    assert not item.cpu_workers
    item.host.initiative_tick.assert_not_called()
    assert persisted(item) == before
