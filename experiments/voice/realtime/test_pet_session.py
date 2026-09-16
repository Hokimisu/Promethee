"""Pet mode keeps one durable brain/world; CPU doubles never start live workers."""

import contextlib
import copy
import hashlib
import json
import queue
import threading
from unittest.mock import Mock

import body
import pytest
from delivery import DirectedWorker
from dialogue import instructions
from test_initiative_session import (
    one_iteration,
    persisted,
    turn_record,
)
from test_initiative_session import (
    session as session,
)
from test_serve import server

from promethee.conversation import ConversationStore
from promethee.execution import ExecutionService
from promethee.initiative import Initiative
from promethee.memory import MemoryStore
from promethee.runtime import Runtime
from promethee.world import ActionError


@pytest.fixture
def pet_session(session, tmp_path):
    item = session
    item.mode = "pet"
    item._body_viewing = False
    service = ExecutionService(
        Runtime(tmp_path / "personal.sqlite3", data_origin="session", session_kind="interactive"),
        clock=lambda: item.cpu_clock[0],
    )
    item.body.service = service
    item.body.poll.side_effect = lambda: {"ready": item.body_ready, "world": service.get_world()}
    item.body.catalog.return_value = {
        "object_models": ["ball", "plush"],
        "object_geometry": {"ball": {"synthetic": True}},
        "supported_interventions": ["spawn"],
        "bounds": {"min": [-4.5, 0, -4.5], "max": [4.5, 5, 4.5]},
    }
    item.initiative = Initiative(service)
    item.host.store = ConversationStore(service)
    item.host.worker_wrapper = lambda worker, request: DirectedWorker(
        worker, request["turn_id"], item.deliveries, allow_silence=True
    )
    item.sid = item.active_sid = ""
    item.state["session_id"] = ""
    return item


def watch(item):
    return item.post("pet_watch", {})


def wake(item):
    watch(item)
    item.post("initiative_configure", {"budget": 3, "interval": 1})
    item.cpu_clock[0] += 1
    item._poll_initiative()
    return item.turn_id


def intervention(item):
    return {
        "request_id": "user-intervention-1",
        "expected_command_revision": item.body.service.get_world()["command_revision"],
        "action": {"kind": "spawn", "args": {"model_id": "ball", "position": [0, 1, 0]}},
    }


def test_watch_does_not_manufacture_message_budget_or_activity(pet_session):
    item = pet_session
    before = copy.deepcopy(item.body.service.runtime.snapshot())
    result = watch(item)
    assert result["session_id"] == item.sid == item.active_sid
    assert item.sid and result["initiative"] is None
    assert result["interrupted"] is False
    assert item.body.service.runtime.snapshot() == before
    assert not item.cpu_workers and not item.auto_continue
    item.body.set_viewing.assert_called_once_with(True)
    assert item.output_deadline == item.cpu_clock[0] + 15
    state = item.snapshot()
    assert state["mode"] == "pet"
    assert state["pet"]["object_geometry"] == {"ball": {"synthetic": True}}
    assert state["pet"]["command_revision"] == item.body.service.get_world()["command_revision"]
    assert state["pet"]["viewing"] is True


def test_watch_preserves_durable_pause_and_does_not_start_body(pet_session):
    item = pet_session
    item.initiative.configure(budget=2, interval=1)
    item.initiative.update(paused=True)
    before = copy.deepcopy(persisted(item))
    watch(item)
    assert persisted(item) == before
    item.body.set_viewing.assert_not_called()
    item.cpu_clock[0] += 1
    item._poll_initiative()
    assert not item.cpu_workers


def test_pet_rejects_forced_scenario_and_watch_payload(pet_session):
    item = pet_session
    with pytest.raises(ValueError, match="scénario"):
        item.post("start", {"scenario": "Scripted performance"})
    with pytest.raises(ValueError, match="scénario"):
        item.post("pet_watch", {"scenario": "Also forbidden"})
    assert not item.cpu_workers and not item.sid


def test_qualification_keeps_pet_endpoints_inaccessible(session):
    for operation in ("pet", "pet_watch"):
        with pytest.raises(ValueError, match="mode pet"):
            session.post(operation, {})
    session.body.intervene.assert_not_called()
    assert session.snapshot()["mode"] == "qualification"
    assert session.snapshot()["pet"] is None


def test_no_audience_suspends_active_initiative_without_persisting_pause(pet_session):
    item = pet_session
    turn = wake(item)
    item.cpu_clock[0] += 16
    item._poll_initiative()
    state = persisted(item)
    assert state["paused"] is False and state["used"] == 1 and state["remaining"] == 2
    assert turn_record(item, turn)[0] == "interrupted"
    assert item.cpu_workers[0].closed and item.host.worker is None
    assert item.turn_source is None and not item.running
    item.body.set_viewing.assert_called_with(False)
    item.body.cancel.assert_not_called()
    item.cpu_clock[0] += 100
    item._poll_initiative()
    assert persisted(item)["used"] == 1
    watch(item)
    item._poll_initiative()
    assert persisted(item)["used"] == 2


def test_lease_expiring_during_presence_wait_cannot_publish_autonomous_audio(pet_session):
    item = pet_session
    turn = wake(item)
    item.body.set_presence.side_effect = lambda _: item.cpu_clock.__setitem__(0, 500)
    item.speak(
        {"id": "voice", "text": "Très bien.", "delivery": "Calm.", "sid": item.sid, "turn_id": turn}
    )
    item.vox_send.assert_not_called()
    assert item.speech is None and not item.events


def test_pause_and_lease_preserve_user_dialogue_authority(pet_session):
    item = pet_session
    watch(item)
    item.post("initiative_configure", {"budget": 3, "interval": 1})
    item.think("Salut.")
    item.running = True
    turn, sid = item.turn_id, item.sid
    item.post("initiative_pause", {"paused": True})
    item.body.set_viewing.assert_called_with(False)
    item.cpu_clock[0] += 16
    item._poll_initiative()
    assert item.sid == sid and turn_record(item, turn)[0] == "running"
    assert not item.cpu_workers[0].closed
    item.body.cancel.assert_not_called()


def test_pet_user_silence_is_native_history_without_vox_or_receipt(pet_session, monkeypatch):
    item = pet_session
    watch(item)
    item.think("Tu peux rester tranquille.")
    item.running = True
    turn = item.turn_id
    item.cpu_workers[0].finish()
    one_iteration(item, monkeypatch)
    status, record = turn_record(item, turn)
    assert status == "completed" and record["trigger"] == "user"
    assert json.loads(record["text"]) == {"silent": True}
    assert record["speech_delivery"] is None
    item.vox_send.assert_not_called()


def test_successful_intervention_fences_old_answer_before_ack_without_cancelling_body(
    pet_session, monkeypatch
):
    item = pet_session
    watch(item)
    item.think("Que vois-tu ?")
    item.running = True
    turn, old_sid = item.turn_id, item.sid
    payload = intervention(item)
    item.body.intervene.return_value = {
        "request_id": payload["request_id"],
        "status": "applied",
        "command_revision": 9,
        "observation": {"synthetic": True},
        "replayed": False,
    }
    result = item.post("pet", payload)
    item.body.intervene.assert_called_once_with(payload)
    assert result["session_id"] == item.sid != old_sid
    assert result["interrupted"] is True and result["command_revision"] == 9
    assert turn_record(item, turn)[0] == "interrupted"
    item.cpu_workers[0].finish('{"text":"Ancien état.","delivery":"Neutral."}')
    one_iteration(item, monkeypatch)
    assert item.active_sid == item.sid and not item.running
    assert item.state["status"] == "Prête" and item.state["phase"] == "idle"
    assert item.state["text"] == ""
    assert item.pending_text is None and item.speech is None
    assert item.cpu_workers[0].closed
    item.body.cancel.assert_not_called()
    item.vox_send.assert_not_called()


@pytest.mark.parametrize("outcome", ["rejected", "replayed", "full_queue"])
def test_refused_or_replayed_intervention_never_cuts_valid_turn(pet_session, monkeypatch, outcome):
    item = pet_session
    watch(item)
    item.think("Salut.")
    item.running = True
    turn, sid = item.turn_id, item.sid
    payload = intervention(item)
    if outcome == "rejected":
        item.body.intervene.side_effect = ActionError("stale command revision")
        with pytest.raises(ActionError):
            item.post("pet", payload)
    elif outcome == "full_queue":
        while not item.commands.full():
            item.commands.put_nowait(("telemetry", {}))
        with pytest.raises(queue.Full):
            item.post("pet", payload)
        item.body.intervene.assert_not_called()
    else:
        item.body.intervene.return_value = {"status": "applied", "replayed": True}
        assert item.post("pet", payload)["interrupted"] is False
    one_iteration(item, monkeypatch)
    assert item.sid == sid and turn_record(item, turn)[0] == "running"
    assert not item.cpu_workers[0].closed
    item.body.cancel.assert_not_called()


def test_body_intervention_requires_live_audience(pet_session):
    item = pet_session
    with pytest.raises(ValueError, match="Ouvre"):
        item.post("pet", intervention(item))
    watch(item)
    item.cpu_clock[0] += 16
    with pytest.raises(ValueError, match="Ouvre"):
        item.post("pet", intervention(item))
    item.body.intervene.assert_not_called()


def test_late_grab_cancel_keeps_current_user_turn(pet_session, monkeypatch):
    item = pet_session
    watch(item)
    item.think("Une nouvelle parole après la saisie.")
    item.running = True
    turn, sid = item.turn_id, item.sid
    payload = intervention(item)
    payload["action"] = {"kind": "grab_cancel", "args": {"grab_id": "older-grab"}}
    item.body.intervene.return_value = {"status": "applied", "replayed": False}
    result = item.post("pet", payload)
    assert result["session_id"] == sid and result["interrupted"] is False
    one_iteration(item, monkeypatch)
    assert turn_record(item, turn)[0] == "running" and not item.cpu_workers[0].closed
    item.body.cancel.assert_not_called()


@pytest.fixture
def personal_config(tmp_path, monkeypatch):
    avatar = tmp_path / "synthetic.vrm"
    avatar.write_bytes(b"CPU-only pet identity fixture")
    monkeypatch.setattr(body, "PIXIV_SHA256", hashlib.sha256(avatar.read_bytes()).hexdigest())
    monkeypatch.setattr(server, "BodyAdapter", body.BodyAdapter)
    monkeypatch.setattr(server.threading, "Thread", Mock(return_value=Mock()))
    return {
        "mode": "pet",
        "brain": "hermes",
        "data_dir": tmp_path / "logs",
        "world_dir": tmp_path / "personal/world",
        "vault": tmp_path / "personal/vault",
        "avatar": avatar,
        "body": {"ardy_python": "unused", "checkpoint_root": "unused"},
        "model": "gpt-5.6-luna",
        "port": 2392,
    }


def test_personal_constructor_binds_new_empty_memory_and_resumes_without_reset(personal_config):
    config = personal_config
    config["initiative"] = {"budget": 4, "interval": 30}
    first = server.Session(config)
    world = first.body.service.runtime.snapshot()
    assert world["session_kind"] == "interactive" and world["data_origin"] == "session"
    assert world["objects"] == {}
    assert first.initiative.service.runtime.snapshot()["initiative"]["paused"] is True
    MemoryStore(first.body.service, config["vault"])
    assert not list((config["vault"] / "Promethee/Memory").iterdir())
    store = ConversationStore(first.body.service)
    request = store.begin("Une histoire synthétique pour vérifier la reprise.")
    store.abort(request["turn_id"], status="interrupted")
    assert first.post("initiative_budget", {"add_budget": 10})["initiative"]["remaining"] == 14
    before = copy.deepcopy(first.body.service.runtime.snapshot())
    original_purpose = (config["world_dir"] / "body-purpose.json").read_bytes()
    first.body.close()
    config["initiative"] = {"budget": 999, "interval": 1}
    resumed = server.Session(config)
    try:
        assert resumed.body.service.runtime.snapshot() == before
        assert resumed.output != first.output
        assert resumed.body.data_dir == first.body.data_dir == config["world_dir"]
        assert resumed.output_deadline == 0
        assert (config["world_dir"] / "body-purpose.json").read_bytes() == original_purpose
        assert (
            ConversationStore(resumed.body.service).service.runtime.snapshot()["world_id"]
            == world["world_id"]
        )
    finally:
        resumed.body.close()


def test_personal_resume_refuses_qualification_before_creating_memory(personal_config):
    config = personal_config
    runtime = Runtime(
        config["world_dir"] / "world.sqlite3", data_origin="session", session_kind="qualification"
    )
    before = copy.deepcopy(runtime.snapshot())
    with pytest.raises((ValueError, ActionError)):
        server.Session(config)
    assert runtime.snapshot() == before and not config["vault"].exists()


def test_pet_prompt_removes_qualification_scope_but_keeps_voice_identity():
    prompt = instructions("pet")
    assert "espace personnel persistant" in prompt
    assert "sans mémoire personnelle" not in prompt
    assert "Les décors ne sont pas manipulables" not in prompt
    assert "moins de 1 m" not in prompt
    assert "objets" in prompt and "mémoire" in prompt
    assert "maximum 24 mots" in prompt and "[Dissatisfaction-hnn]" in prompt
    assert '{"silent": true}' in prompt
    assert "sans mémoire personnelle" in instructions()


def test_pet_uses_same_hermes_host_with_bound_vault_and_silence_contract(
    pet_session, tmp_path, monkeypatch
):
    item = pet_session
    item.config = {
        "brain": "hermes",
        "resident": True,
        "world_context": True,
        "vault": tmp_path / "explicit-vault",
        "voice_command": ["never-launched"],
    }
    item.model, item.voice_profile = "gpt-5.6-luna", "unchanged-reference"
    item.body.data_dir = tmp_path / "personal-world"
    process = Mock()
    monkeypatch.setattr(server.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(server.threading, "Thread", Mock(return_value=Mock()))
    native = Mock(return_value=contextlib.nullcontext(item.host))
    monkeypatch.setattr(server, "open_text_host", native)
    item.loop = Mock()
    item.run()
    native.assert_called_once()
    args = native.call_args.args[0]
    assert args.data_dir == item.body.data_dir and args.vault == item.config["vault"]
    assert args.system_message == instructions("pet")
    assert args.model == "gpt-5.6-luna" and args.auth == "hermes-codex"
    assert args.resident and args.world_context and args.reasoning_effort == "low"
    wrapper = item.host.worker_wrapper(Mock(), {"turn_id": "a-user-turn"})
    assert wrapper.allow_silence is True
    item.loop.assert_called_once()


def test_pause_ack_cannot_be_overtaken_by_an_old_observed_viewing_state(pet_session):
    item = pet_session
    watch(item)
    item.post("initiative_configure", {"budget": 3, "interval": 10})
    read, release, attempted, acknowledged = (threading.Event() for _ in range(4))
    failures = []
    observe = item.initiative.observe

    def gated_observe():
        result = observe()
        read.set()
        assert release.wait(2), "test did not release the observed snapshot"
        return result

    def poll():
        try:
            item._poll_initiative()
        except BaseException as exc:
            failures.append(exc)

    def pause():
        attempted.set()
        try:
            item.post("initiative_pause", {"paused": True})
            acknowledged.set()
        except BaseException as exc:
            failures.append(exc)

    item.initiative.observe = gated_observe
    owner, requester = threading.Thread(target=poll), threading.Thread(target=pause)
    owner.start()
    try:
        assert read.wait(2)
        requester.start()
        assert attempted.wait(2)
        serialized = not acknowledged.wait(0.05)
    finally:
        release.set()
        owner.join(2)
        if requester.ident is not None:
            requester.join(2)
    assert not failures and not owner.is_alive() and not requester.is_alive()
    assert serialized and acknowledged.is_set()
    assert persisted(item)["paused"] is True
    item.body.set_viewing.assert_called_with(False)
    assert item._body_viewing is False and not item.cpu_workers


def test_old_tab_heartbeat_cannot_renew_a_new_stopped_session(pet_session, monkeypatch):
    item = pet_session
    watch(item)
    old_sid = item.sid
    read, release, attempted, acknowledged = (threading.Event() for _ in range(4))
    failures = []

    class GatedTelemetry(dict):
        def get(self, key, default=None):
            if key == "event":
                read.set()
                assert release.wait(2), "test did not release the old heartbeat"
            return super().get(key, default)

    item.post("telemetry", GatedTelemetry(session_id=old_sid, event="client_stats"))

    def poll():
        try:
            one_iteration(item, monkeypatch)
        except BaseException as exc:
            failures.append(exc)

    def stop():
        attempted.set()
        try:
            item.post("stop", {})
            acknowledged.set()
        except BaseException as exc:
            failures.append(exc)

    owner, requester = threading.Thread(target=poll), threading.Thread(target=stop)
    owner.start()
    try:
        assert read.wait(2)
        requester.start()
        assert attempted.wait(2)
        serialized = not acknowledged.wait(0.05)
    finally:
        release.set()
        owner.join(2)
        if requester.ident is not None:
            requester.join(2)
    assert not failures and not owner.is_alive() and not requester.is_alive()
    assert serialized and acknowledged.is_set()
    assert item.sid != old_sid and item.output_deadline == 0
    assert item._body_viewing is False


@pytest.mark.parametrize("paused", [False, True])
def test_budget_top_up_does_not_enable_audience_or_change_pause(pet_session, paused):
    item = pet_session
    item.initiative.configure(budget=1, interval=4)
    item.initiative.update(paused=paused)
    before = copy.deepcopy(persisted(item))
    result = item.post("initiative_budget", {"add_budget": 10})
    assert result == {
        "initiative": {**before, "remaining": 11},
        "session_id": "",
        "cursor": item.cursor,
        "interrupted": False,
    }
    assert not item.sid and item.output_deadline == 0
    assert not item.cpu_workers and item.commands.empty()
    item.body.set_viewing.assert_not_called()
    item.body.cancel.assert_not_called()


@pytest.mark.parametrize("source", ["user", "initiative"])
def test_budget_top_up_preserves_current_turn_and_ui_fence(pet_session, source):
    item = pet_session
    if source == "initiative":
        turn = wake(item)
    else:
        watch(item)
        item.initiative.configure(budget=3, interval=10)
        item.think("Une parole en cours.")
        turn = item.turn_id
    before = copy.deepcopy(persisted(item))
    sid, deadline, worker = item.sid, item.output_deadline, item.cpu_workers[-1]
    result = item.post("initiative_budget", {"add_budget": 10})
    assert result["initiative"] == {**before, "remaining": before["remaining"] + 10}
    assert result["session_id"] == sid and result["interrupted"] is False
    assert item.sid == sid and item.output_deadline == deadline
    assert turn_record(item, turn)[0] == "running" and not worker.closed
    assert item.host.worker is not None
    item.body.cancel.assert_not_called()


def test_exhausted_budget_can_be_replenished_and_survives_reopen(pet_session, monkeypatch):
    item = pet_session
    watch(item)
    item.post("initiative_configure", {"budget": 1, "interval": 1})
    item.cpu_clock[0] += 1
    item._poll_initiative()
    item.cpu_workers[-1].finish()
    one_iteration(item, monkeypatch)
    assert persisted(item)["used"] == 1 and persisted(item)["remaining"] == 0
    item.post("initiative_pause", {"paused": True})
    item.post("initiative_budget", {"add_budget": 10})
    before = copy.deepcopy(persisted(item))
    reopened = Runtime(
        item.body.service.runtime.path,
        data_origin="session",
        session_kind="interactive",
        create=False,
    )
    assert reopened.snapshot()["initiative"] == before
    assert before["remaining"] == 10 and before["used"] == 1 and before["paused"] is True


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"add_budget": None},
        {"add_budget": True},
        {"add_budget": 0},
        {"add_budget": -1},
        {"add_budget": 1001},
        {"add_budget": 999},
        {"add_budget": 10.0},
        {"add_budget": "10"},
        {"add_budget": float("nan")},
        {"add_budget": 10, "paused": False},
    ],
)
def test_invalid_budget_additions_have_no_effect(pet_session, payload):
    item = pet_session
    item.initiative.configure(budget=2, interval=4)
    item.initiative.update(paused=True)
    before = copy.deepcopy(item.body.service.runtime.snapshot())
    with pytest.raises((ValueError, ActionError)):
        item.post("initiative_budget", payload)
    assert item.body.service.runtime.snapshot() == before
    assert not item.sid and item.output_deadline == 0
    item.body.set_viewing.assert_not_called()


def test_budget_top_up_requires_existing_configuration_and_pet_mode(pet_session):
    with pytest.raises(ActionError, match="not configured"):
        pet_session.post("initiative_budget", {"add_budget": 10})
    pet_session.mode = "qualification"
    with pytest.raises(ValueError, match="mode pet"):
        pet_session.post("initiative_budget", {"add_budget": 10})
