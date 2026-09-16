"""Synthetic microphone contracts; never open a device or construct a live model."""

import base64
import collections
import copy
import json
import queue
import threading
from http.client import HTTPConnection
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from asr import MAX_PCM_BYTES, validate_audio
from test_serve import http_server as http_server
from test_serve import server

from promethee.conversation import ConversationStore
from promethee.execution import ExecutionService
from promethee.initiative import Initiative
from promethee.runtime import Runtime
from promethee.world import ActionError

INPUT_ID = "input-12345678-1234-1234-1234-123456789abc"
NEXT_INPUT_ID = "input-87654321-4321-4321-4321-cba987654321"
PCM = base64.b64encode(b"\1\0" * 160).decode("ascii")


@pytest.fixture
def micro_session(tmp_path):
    """Real durable turn store with fake workers; bypass every live constructor."""
    item = server.Session.__new__(server.Session)
    item.lock = threading.RLock()
    item.commands = queue.Queue(maxsize=1)
    item.events = collections.deque(maxlen=640)
    item.cursor = 0
    item.sid = item.active_sid = "existing-session"
    item.state = {"session_id": item.sid, "phase": "speaking"}
    item.vox_ready = True
    item.snapshot = Mock(return_value={"ready": True})
    item.body = Mock()
    item.vox_send = Mock()
    item.speech = None
    item.pending_text = None
    item.pending_audio = None
    item.input_capture = None
    item.input_ids = set()
    item.running = True
    item.auto_continue = True
    item.turn_source = "user"
    item.output_deadline = 0
    item.began = 1.0
    item.calls = 0
    service = ExecutionService(
        Runtime(tmp_path / "world.sqlite3", data_origin="session", session_kind="qualification"),
        clock=lambda: 100.0,
    )
    store = ConversationStore(service)
    item.initiative = Initiative(service)
    opened = store.begin("Existing user input")
    item.turn_id = opened["turn_id"]
    item.host = Mock()
    item.host.store = store
    item.host.cancel.side_effect = lambda: store.abort(item.turn_id, status="interrupted")
    item.host.start.side_effect = lambda message: store.begin(message)["turn_id"]
    item.asr = SimpleNamespace(
        state="ready", error=None, busy=False, poll=Mock(return_value=None), submit=Mock()
    )
    item.asr_status = {"state": "ready", "error": None}

    def submitted(*_args):
        item.asr.busy = True

    item.asr.submit.side_effect = submitted
    return item


def owner_input(item):
    operation, value = item.commands.get_nowait()
    if value["session_id"] == item.sid:
        item.active_sid = item.sid
        item._handle_input(operation, value)
    return operation, value


def start_input(item, input_id=INPUT_ID):
    result = item.post("input_start", {"input_id": input_id})
    owner_input(item)
    return result


def audio_value(item):
    return {
        "input_id": item.input_capture["input_id"],
        "session_id": item.sid,
        "sample_rate": 16000,
        "pcm16": PCM,
    }


def transcribing(item):
    start_input(item)
    value = audio_value(item)
    item.post("input_audio", value)
    owner_input(item)
    item._poll_input()
    return value


def test_input_start_fences_real_turn_before_ack_and_before_worker_cleanup(micro_session):
    item = micro_session
    old_turn = item.turn_id
    result = item.post("input_start", {"input_id": INPUT_ID})
    assert result["session_id"] == item.sid != "existing-session"
    assert result["input_id"] == INPUT_ID
    assert item.input_capture["state"] == "listening"
    assert item.host.store.service.get_world()["conversation"] is None
    with pytest.raises(ActionError, match="obsolete|expired"):
        item.host.store.service.end_turn(old_turn)
    with pytest.raises(ActionError, match="obsolete|expired"):
        item.host.store.service.submit(
            "late-tool",
            item.host.store.service.get_world()["revision"],
            {"kind": "move", "args": {"position": [0.2, 0]}},
            turn_id=old_turn,
        )
    item.host.cancel.assert_not_called()
    item.body.cancel.assert_not_called()
    item.asr.submit.assert_not_called()
    owner_input(item)
    item.host.cancel.assert_called_once()
    item.body.cancel.assert_not_called()
    assert not item.auto_continue and not item.running
    assert list(item.events) == []


@pytest.mark.parametrize("phase", ["accepted", "running"])
def test_microphone_interruption_preserves_an_accepted_body_action(micro_session, phase):
    item = micro_session
    service = item.host.store.service
    handle = service.acquire_controller(source="kinematic", supported_actions=["move"])
    world = service.runtime.snapshot()
    observation = {key: copy.deepcopy(world[key]) for key in ("avatar", "objects")}
    observation["pose"] = {
        "skeleton": "cskel27",
        "positions": [[0.0, 1.0, 0.0] for _ in range(27)],
        "rotations": [[[1, 0, 0], [0, 1, 0], [0, 0, 1]] for _ in range(27)],
    }
    assert handle.reconcile(observation, stopped=True)
    service.submit(
        "moving",
        service.get_world()["revision"],
        {"kind": "move", "args": {"position": [0.2, 0]}},
        turn_id=item.turn_id,
    )
    if phase == "running":
        assert handle.claim_next()["request_id"] == "moving"
        assert handle.feedback("moving", 0, "running", observation=observation)
    before = service.get("moving")
    start_input(item)
    assert service.get("moving") == before
    assert service.get_world()["pose"] == observation["pose"]
    item.body.cancel.assert_not_called()


def test_full_input_queue_cannot_fence_the_turn_or_change_capture(micro_session):
    item = micro_session
    item.commands.put_nowait(("occupied", {}))
    before = copy.deepcopy((item.sid, item.state, item.input_capture, item.input_ids))
    world = item.host.store.service.get_world()
    with pytest.raises(queue.Full):
        item.post("input_start", {"input_id": INPUT_ID})
    assert (item.sid, item.state, item.input_capture, item.input_ids) == before
    assert item.host.store.service.get_world() == world
    item.host.cancel.assert_not_called()


@pytest.mark.parametrize("operation", ["input_audio", "input_cancel"])
def test_full_queue_preserves_a_listening_capture(micro_session, operation):
    item = micro_session
    start_input(item)
    item.commands.put_nowait(("occupied", {}))
    before = copy.deepcopy((item.sid, item.state, item.input_capture))
    with pytest.raises(queue.Full):
        item.post(operation, audio_value(item))
    assert (item.sid, item.state, item.input_capture) == before
    item.asr.submit.assert_not_called()


def test_repeated_start_and_audio_do_not_duplicate_transcription_or_turn(micro_session):
    item = micro_session
    result = start_input(item)
    assert item.post("input_start", {"input_id": INPUT_ID}) == result
    assert item.commands.empty()
    value = audio_value(item)
    item.post("input_audio", value)
    assert item.post("input_audio", value)["replayed"]
    assert item.commands.qsize() == 1
    with pytest.raises(ValueError):
        item.post("input_audio", {**value, "pcm16": base64.b64encode(b"\2\0").decode()})
    owner_input(item)
    item._poll_input()
    item.asr.submit.assert_called_once_with(result["session_id"], PCM)
    item.asr.busy = False
    item.asr.poll.return_value = {"event": "transcript", "id": item.sid, "text": "Bonjour."}
    item._poll_input()
    item._poll_input()
    assert item.post("input_audio", value)["replayed"]
    item.host.start.assert_called_once_with("Message : Bonjour.")
    assert item.input_capture["state"] == "completed"
    assert not item.auto_continue
    assert item.commands.empty()


@pytest.mark.parametrize("replacement", ["input_start", "say", "stop"])
def test_late_transcription_cannot_resurrect_replaced_input(micro_session, replacement):
    item = micro_session
    value = transcribing(item)
    if replacement == "input_start":
        item.post(replacement, {"input_id": NEXT_INPUT_ID})
    else:
        item.post(replacement, {"text": "Correction écrite"} if replacement == "say" else {})
    new_sid = item.sid
    item.asr.busy = False
    item.asr.poll.return_value = {
        "event": "transcript",
        "id": value["session_id"],
        "text": "Ancien enregistrement",
    }
    item._poll_input()
    assert item.sid == new_sid != value["session_id"]
    item.host.start.assert_not_called()
    with pytest.raises(ValueError):
        item.post("input_audio", value)


def test_new_audio_waits_for_old_asr_cleanup_without_replaying_old_text(micro_session):
    item = micro_session
    old = transcribing(item)
    start_input(item, NEXT_INPUT_ID)
    new = audio_value(item)
    item.post("input_audio", new)
    owner_input(item)
    item._poll_input()
    assert item.pending_audio == new
    assert item.asr.submit.call_count == 1

    item.asr.busy = False
    item.asr.poll.return_value = {
        "event": "transcript",
        "id": old["session_id"],
        "text": "Ancienne parole",
    }
    item._poll_input()
    item.host.start.assert_not_called()
    assert item.pending_audio is None
    assert item.asr.submit.call_count == 2
    item.asr.submit.assert_called_with(new["session_id"], PCM)

    item.asr.busy = False
    item.asr.poll.return_value = {
        "event": "transcript",
        "id": new["session_id"],
        "text": "Nouvelle parole",
    }
    item._poll_input()
    item.host.start.assert_called_once_with("Message : Nouvelle parole")


def test_old_cancel_cannot_cancel_the_new_capture(micro_session):
    item = micro_session
    old = start_input(item)
    start_input(item, NEXT_INPUT_ID)
    before = copy.deepcopy((item.sid, item.state, item.input_capture))
    with pytest.raises(ValueError):
        item.post("input_cancel", old)
    assert (item.sid, item.state, item.input_capture) == before
    assert item.commands.empty()


def test_cancel_keeps_session_but_rejects_late_asr_result(micro_session):
    item = micro_session
    value = transcribing(item)
    result = item.post("input_cancel", {"input_id": INPUT_ID, "session_id": item.sid})
    assert result["session_id"] == value["session_id"] == item.sid
    owner_input(item)
    assert item.input_capture["state"] == "cancelled"
    item.asr.busy = False
    item.asr.poll.return_value = {"event": "transcript", "id": item.sid, "text": "Too late"}
    item._poll_input()
    item.host.start.assert_not_called()
    item.body.cancel.assert_not_called()
    assert item.state["phase"] == "idle"


@pytest.mark.parametrize("failure", ["empty", "too-long", "provider", "deadline"])
def test_asr_failure_keeps_text_entry_available(micro_session, failure):
    item = micro_session
    transcribing(item)
    if failure == "deadline":
        item.input_capture["deadline"] = 0
    else:
        item.asr.busy = False
        item.asr.poll.return_value = {
            "event": "error" if failure == "provider" else "transcript",
            "id": item.sid,
            "text": " " if failure == "empty" else "x" * 1201,
        }
    item._poll_input()
    assert item.input_capture["state"] == "failed"
    assert item.state["phase"] == "idle"
    item.host.start.assert_not_called()
    result = item.post("say", {"text": "Je continue en texte."})
    assert result["session_id"] == item.sid
    assert item.commands.get_nowait()[0] == "say"


@pytest.mark.parametrize("state", ["disabled", "loading", "failed"])
def test_unavailable_asr_does_not_break_text_or_open_microphone(micro_session, state):
    item = micro_session
    item.asr.state = state
    previous = item.sid
    with pytest.raises(ValueError):
        item.post("input_start", {"input_id": INPUT_ID})
    assert item.sid == previous
    assert item.input_capture is None
    item.asr.submit.assert_not_called()
    assert item.post("say", {"text": "Texte disponible."})["session_id"] != previous


def test_old_cleanup_cannot_start_a_turn_after_new_input_fence(micro_session):
    item = micro_session
    old_sid = item.sid
    item.post("input_start", {"input_id": INPUT_ID})
    item.think("Ancienne réponse", expected_sid=old_sid)
    item.host.start.assert_not_called()
    assert item.host.store.service.get_world()["conversation"] is None


def one_owner_iteration(item):
    """Exercise the real loop once with workers and disk writes disabled."""
    item.stopping = threading.Event()
    item.vox_events = queue.Queue()
    item.deliveries = {}
    item.metric = {"brain_seconds": [], "brain_timings": [], "voice_runs": []}
    item.brain_started = 0
    item.next_brain_warm = 0
    item.next_metrics_write = float("inf")
    item.host.worker = None
    item.host.poll.return_value = None
    item.host.warm_status.return_value = {"state": "ready"}
    item.body.poll.return_value = {"ready": True}

    def warmed():
        item.stopping.set()
        return {"state": "ready"}

    item.host.warm.side_effect = warmed


@pytest.mark.parametrize("kind", ["pcm", "done", "cancelled"])
def test_voice_publication_cannot_relabel_old_audio_after_microphone_ack(micro_session, kind):
    item = micro_session
    one_owner_iteration(item)
    item.auto_continue = False
    item.speech = {
        "id": "old-speech",
        "sid": item.sid,
        "turn_id": item.turn_id,
        "samples": 0,
        "first": 1.0,
        "done": False,
        "end_estimate": float("inf"),
        "terminal": False,
    }
    item.vox_events.put_nowait(
        {"event": kind, "id": "old-speech", "samples": 160, "pcm_f32_b64": "AAAAAA=="}
    )
    original_emit = item.emit
    attempted, acknowledged = threading.Event(), threading.Event()
    outcome = {}

    def post_input():
        attempted.set()
        try:
            outcome["ack"] = item.post("input_start", {"input_id": INPUT_ID})
        except Exception as exc:
            outcome["error"] = exc
        finally:
            acknowledged.set()

    poster = threading.Thread(target=post_input, daemon=True)

    def interleaved_emit(event, **fields):
        # The scheduling point is after the old SID check, just before publication.
        # With atomic publication the HTTP thread waits for the owning lock instead.
        atomic = item.lock._is_owned()
        poster.start()
        assert attempted.wait(3)
        if not atomic:
            assert acknowledged.wait(3)
        original_emit(event, **fields)

    item.emit = interleaved_emit
    item.loop()
    poster.join(timeout=3)
    assert acknowledged.is_set() and not poster.is_alive()
    assert "error" not in outcome
    new_sid = outcome["ack"]["session_id"]
    assert not any(
        event["session_id"] == new_sid and event.get("id") == "old-speech" for event in item.events
    )
    assert item.state["phase"] == "listening"
    item.body.cancel.assert_not_called()


@pytest.mark.parametrize("status", ["interrupted", "failed"])
def test_old_brain_failure_cannot_overwrite_new_microphone_state(micro_session, status):
    item = micro_session
    one_owner_iteration(item)

    def poll_while_user_starts_speaking():
        # Native poll can close a worker and release the GIL while HTTP fences it.
        item.post("input_start", {"input_id": INPUT_ID})
        return {"status": status, "code": "obsolete_response"}

    item.host.poll.side_effect = poll_while_user_starts_speaking
    item.loop()
    assert item.state["phase"] == "listening"
    assert item.input_capture["state"] == "listening"
    assert item.state.get("error") is None
    item.host.start.assert_not_called()


@pytest.mark.parametrize("scene", ["expired-scenario", "finished-single-response"])
def test_microphone_fence_prevents_stale_scene_housekeeping(micro_session, scene):
    item = micro_session
    one_owner_iteration(item)
    item.auto_continue = scene == "expired-scenario"
    item.began = server.time.monotonic() - 61

    def poll_while_user_starts_speaking():
        item.post("input_start", {"input_id": INPUT_ID})
        return None

    item.host.poll.side_effect = poll_while_user_starts_speaking
    item.loop()
    item.body.cancel.assert_not_called()
    item.body.set_presence.assert_not_called()
    assert list(item.events) == []
    assert item.state["phase"] == "listening"


def test_single_response_completion_disables_gestures_without_cancelling_body(micro_session):
    item = micro_session
    one_owner_iteration(item)
    item.auto_continue = False
    item.speech = {
        "id": "finished-speech",
        "sid": item.sid,
        "turn_id": item.turn_id,
        "done": True,
        "terminal": True,
        "end_estimate": float("inf"),
    }
    item.loop()
    assert item.speech is None
    assert not item.running
    assert item.state["phase"] == "idle"
    item.body.set_presence.assert_called_once_with(False)
    item.body.cancel.assert_not_called()
    assert list(item.events) == []


def test_stop_status_cannot_overwrite_a_new_microphone_capture(micro_session):
    item = micro_session
    one_owner_iteration(item)
    item.post("stop", {})
    original_update = item.update
    attempted, acknowledged = threading.Event(), threading.Event()
    outcome = {}

    def post_input():
        attempted.set()
        try:
            outcome["ack"] = item.post("input_start", {"input_id": INPUT_ID})
        except Exception as exc:
            outcome["error"] = exc
        finally:
            acknowledged.set()

    poster = threading.Thread(target=post_input, daemon=True)

    def interleaved_update(**fields):
        if fields.get("status") == "Essai arrêté":
            atomic = item.lock._is_owned()
            poster.start()
            assert attempted.wait(3)
            if not atomic:
                assert acknowledged.wait(3)
        original_update(**fields)

    item.update = interleaved_update
    item.loop()
    poster.join(timeout=3)
    assert acknowledged.is_set() and not poster.is_alive()
    assert "error" not in outcome
    assert item.input_capture["state"] == "listening"
    assert item.state["phase"] == "listening"


@pytest.mark.parametrize("size", [2, MAX_PCM_BYTES])
def test_pcm16_boundary_preserves_valid_audio_bytes(size):
    pcm = b"\1\0" * (size // 2)
    assert (
        validate_audio({"sample_rate": 16000, "pcm16": base64.b64encode(pcm).decode("ascii")})
        == pcm
    )


@pytest.mark.parametrize("sample_rate", [None, True, 16000.0, "16000", 24000, 48000])
def test_pcm16_boundary_refuses_an_ambiguous_sample_rate(sample_rate):
    with pytest.raises(ValueError):
        validate_audio({"sample_rate": sample_rate, "pcm16": "AAA="})


@pytest.mark.parametrize(
    "pcm16",
    [
        None,
        "",
        "!!!!",
        "AAA=\n",
        base64.b64encode(b"\0").decode("ascii"),
        base64.b64encode(b"\0" * 3).decode("ascii"),
        base64.b64encode(b"\0" * (MAX_PCM_BYTES + 2)).decode("ascii"),
    ],
    ids=["missing", "empty", "invalid-base64", "newline", "one-byte", "odd", "too-long"],
)
def test_pcm16_boundary_refuses_empty_malformed_odd_or_oversized_audio(pcm16):
    with pytest.raises(ValueError):
        validate_audio({"sample_rate": 16000, "pcm16": pcm16})


def test_http_audio_accepts_one_bounded_segment_larger_than_control_messages(http_server):
    httpd, session = http_server
    port = httpd.server_address[1]
    connection = HTTPConnection("127.0.0.1", port, timeout=3)
    value = {
        "input_id": INPUT_ID,
        "session_id": "cpu-session",
        "sample_rate": 16000,
        "pcm16": base64.b64encode(b"\0\0" * (16000 * 12)).decode("ascii"),
    }
    try:
        connection.request(
            "POST",
            "/input_audio",
            body=json.dumps(value),
            headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"},
        )
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read()) == {"ok": True}
        session.post.assert_called_once_with("input_audio", value)
    finally:
        connection.close()


@pytest.mark.parametrize("path", ["/say", "/input_start", "/input_cancel"])
def test_http_audio_allowance_does_not_expand_control_messages(http_server, path):
    httpd, session = http_server
    port = httpd.server_address[1]
    connection = HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request(
            "POST",
            path,
            body="{}",
            headers={
                "Content-Type": "application/json",
                "Origin": f"http://127.0.0.1:{port}",
                "Content-Length": "20000",
            },
        )
        response = connection.getresponse()
        assert response.status in (400, 413)
        assert response.will_close
        response.read()
        session.post.assert_not_called()
    finally:
        connection.close()


@pytest.mark.parametrize(
    "headers,status",
    [
        ({"Origin": "http://unexpected.invalid"}, 403),
        ({"Content-Type": "text/plain"}, 400),
        ({"Transfer-Encoding": "chunked"}, 400),
        ({"Content-Length": "2000000"}, 400),
    ],
)
def test_http_audio_rejects_unbounded_or_wrong_origin_input(http_server, headers, status):
    httpd, session = http_server
    port = httpd.server_address[1]
    connection = HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request(
            "POST",
            "/input_audio",
            body="{}",
            headers={
                "Content-Type": "application/json",
                "Origin": f"http://127.0.0.1:{port}",
                **headers,
            },
        )
        response = connection.getresponse()
        assert response.status == status
        assert response.will_close
        response.read()
        session.post.assert_not_called()
    finally:
        connection.close()
