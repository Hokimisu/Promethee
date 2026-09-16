"""Command guards tolerate explicit idle pose updates, never changed world authority."""

import copy
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import Clock
from test_appearance_checkpoint import observed

from promethee.appearance_checkpoint import pose_digest
from promethee.execution import ExecutionService
from promethee.runtime import Runtime, encode
from promethee.world import ActionError

MOVE = {"kind": "move", "args": {"position": [1, 0]}}


@pytest.fixture
def command_body(tmp_path, articulated_pose):
    clock = Clock()
    service = ExecutionService(
        Runtime(tmp_path / "world.sqlite3", data_origin="session", session_kind="qualification"),
        clock=clock,
    )
    handle = service.acquire_controller(
        source="kinematic", supported_actions=["move", "posture", "write", "take"]
    )
    initial = observed(articulated_pose)
    initial["objects"] = {
        "note": {"asset": "sign", "position": [0.5, 0], "text": "Original"},
        "seat": {"asset": "chair", "position": [0, 0]},
        "toy": {"asset": "plush", "position": [0, 0]},
    }
    assert handle.reconcile(initial, stopped=True)
    return service, handle, clock, initial


def shifted(initial, offset):
    value = copy.deepcopy(initial)
    for point in value["pose"]["positions"]:
        point[0] += offset
    value["avatar"]["position"][0] += offset
    value["appearance"]["core_pose_sha256"] = pose_digest(value["pose"])
    return value


def submit_command(service, request_id, revision, action=MOVE, **options):
    return service.submit(request_id, action=action, expected_command_revision=revision, **options)


def test_pose_updates_preserve_command_guard_but_not_strict_guard(command_body):
    service, handle, clock, initial = command_body
    before = service.get_world()
    for offset in (0.01, 0.02, 0.03):
        clock.advance(0.1)
        candidate = shifted(initial, offset)
        assert handle.observe_idle(candidate)
    current = service.get_world()
    assert current["revision"] == before["revision"] + 3
    assert current["idle_pose_updates"] == before["idle_pose_updates"] + 3
    assert current["command_revision"] == before["command_revision"]
    strict = service.submit("strict", before["revision"], MOVE)
    assert strict["error"]["code"] == "revision_conflict"
    item = submit_command(service, "command", before["command_revision"])
    assert item["status"] == "accepted"
    assert item["validated_revision"] == current["revision"]
    assert item["validated_command_revision"] == current["command_revision"]
    assert item["envelope"] == {
        "request_id": "command",
        "expected_command_revision": before["command_revision"],
        "action": MOVE,
    }
    assert {key: service.get_world()[key] for key in candidate} == candidate
    assert handle.claim_next()["request_id"] == "command"
    with pytest.raises(ActionError, match="execution is active"):
        handle.observe_idle(shifted(initial, 0.04))


def test_strict_envelope_remains_unchanged(command_body):
    service, _, _, _ = command_body
    before = service.get_world()
    item = service.submit("strict", before["revision"], MOVE)
    assert item["envelope"] == {
        "request_id": "strict",
        "expected_revision": before["revision"],
        "action": MOVE,
    }
    assert item["validated_revision"] == before["revision"]
    assert item["validated_command_revision"] == before["command_revision"]


@pytest.mark.parametrize("guard", [{}, {"expected_revision": 0, "expected_command_revision": 0}])
def test_exactly_one_revision_guard_is_required(command_body, guard):
    service, _, _, _ = command_body
    before = service.get_world(), service.events()
    with pytest.raises(ActionError):
        service.submit("invalid", action=MOVE, **guard)
    assert (service.get_world(), service.events()) == before


@pytest.mark.parametrize("revision", [-1, True, 1.5, "1"])
def test_command_guard_is_a_nonnegative_strict_integer(command_body, revision):
    service, _, _, _ = command_body
    with pytest.raises(ActionError):
        submit_command(service, "invalid", revision)
    assert service.events() == []


@pytest.mark.parametrize(
    "mutation",
    ["spawn", "delete", "move-object", "write", "holding", "seated", "mode", "version", "scale"],
)
def test_non_pose_changes_through_idle_invalidate_old_command_guard(command_body, mutation):
    service, handle, _, initial = command_body
    before = service.get_world()
    changed = copy.deepcopy(initial)
    if mutation == "spawn":
        changed["objects"]["ball"] = {"asset": "ball", "position": [1, 0]}
    elif mutation == "delete":
        del changed["objects"]["note"]
    elif mutation == "move-object":
        changed["objects"]["note"]["position"] = [0.6, 0]
    elif mutation == "write":
        changed["objects"]["note"]["text"] = "Changed"
    elif mutation == "holding":
        changed["avatar"]["holding"] = "toy"
    elif mutation == "seated":
        changed["avatar"]["seated_on"] = "seat"
    elif mutation == "mode":
        changed["appearance"]["mode"] = "--plant"
    elif mutation == "scale":
        # Valid checkpoint tolerance does not make changed identity an idle pose.
        changed["appearance"]["scale"] += 1e-9
    else:
        changed["appearance"].update(version=2, alignment_weights={"RightHand": 0, "LeftHand": 0})
    assert handle.observe_idle(changed)
    after = service.get_world()
    assert after["idle_pose_updates"] == before["idle_pose_updates"]
    assert after["command_revision"] == before["command_revision"] + 1
    assert submit_command(service, "stale", before["command_revision"])["status"] == "rejected"
    assert service.get_world() == after


def test_object_changed_then_restored_cannot_revalidate_old_guard(command_body):
    service, handle, _, initial = command_body
    before = service.get_world()
    changed = copy.deepcopy(initial)
    changed["objects"]["note"]["text"] = "Temporary"
    assert handle.observe_idle(changed)
    assert handle.observe_idle(initial)
    after = service.get_world()
    assert after["objects"] == before["objects"]
    assert after["command_revision"] == before["command_revision"] + 2
    assert submit_command(service, "stale", before["command_revision"])["status"] == "rejected"


def test_identical_idle_is_not_counted_but_new_observation_time_is(command_body):
    service, handle, clock, initial = command_body
    before = service.get_world()
    assert handle.observe_idle(initial)
    assert service.get_world() == before
    clock.advance(0.25)
    assert handle.observe_idle(initial)
    after = service.get_world()
    assert after["revision"] == before["revision"] + 1
    assert after["idle_pose_updates"] == before["idle_pose_updates"] + 1
    assert after["command_revision"] == before["command_revision"]


@pytest.mark.parametrize("mutation", ["joint", "frame", "aligned_hands", "weights"])
def test_visible_pose_changes_keep_the_command_guard(command_body, mutation):
    service, handle, _, initial = command_body
    if mutation == "weights":
        initial = copy.deepcopy(initial)
        initial["appearance"].update(version=2, alignment_weights={"RightHand": 0, "LeftHand": 0})
        assert handle.reconcile(initial, stopped=True)
    before = service.get_world()
    changed = copy.deepcopy(initial)
    if mutation == "joint":
        changed["pose"]["positions"][3][1] += 0.01
        changed["appearance"]["core_pose_sha256"] = pose_digest(changed["pose"])
    elif mutation == "frame":
        changed["appearance"]["frame"]["root_y_offset"] += 0.001
    elif mutation == "aligned_hands":
        changed["appearance"]["aligned_hands"] = ["RightHand"]
    else:
        changed["appearance"]["alignment_weights"]["RightHand"] = 0.4
    assert handle.observe_idle(changed)
    after = service.get_world()
    assert after["revision"] == before["revision"] + 1
    assert after["idle_pose_updates"] == before["idle_pose_updates"] + 1
    assert after["command_revision"] == before["command_revision"]
    assert {key: after[key] for key in changed} == changed


def test_body_confirmation_and_replacement_capabilities_invalidate_guard(command_body):
    service, handle, _, initial = command_body
    before = service.get_world()
    assert handle.release()
    replacement = service.acquire_controller(source="kinematic", supported_actions=["posture"])
    unconfirmed = service.get_world()
    rejected = submit_command(service, "unconfirmed", unconfirmed["command_revision"])
    assert rejected["error"]["code"] == "controller_unavailable"
    assert replacement.observe_idle(initial)
    confirmed = service.get_world()
    assert confirmed["idle_pose_updates"] == before["idle_pose_updates"]
    assert confirmed["command_revision"] > before["command_revision"]
    assert submit_command(service, "stale", before["command_revision"])["status"] == "rejected"
    unsupported = submit_command(service, "unsupported", confirmed["command_revision"])
    assert unsupported["error"]["code"] == "invalid_action"
    assert handle.observe_idle(initial) is False


def test_lease_expiry_still_rejects_command_after_pose_update(command_body):
    service, handle, clock, initial = command_body
    before = service.get_world()
    clock.advance(4.9)
    assert handle.observe_idle(shifted(initial, 0.01))
    clock.advance(0.1)
    assert submit_command(service, "expired", before["command_revision"])["status"] == "rejected"
    assert service.get_world()["body"]["status"] == "unconfirmed"


@pytest.mark.parametrize("mutation", ["replace", "expire"])
def test_new_guard_cannot_bypass_conversation_authority(command_body, mutation):
    service, handle, clock, initial = command_body
    turn = service.begin_turn(timeout=0.5)
    before = service.get_world()
    assert handle.observe_idle(shifted(initial, 0.01))
    if mutation == "replace":
        service.begin_turn()
    else:
        clock.advance(0.5)
    with pytest.raises(ActionError, match="obsolete|expired"):
        submit_command(service, "late", before["command_revision"], turn_id=turn)
    assert service.events() == []


def test_current_pose_still_controls_reach_validation(command_body):
    service, handle, _, initial = command_body
    before = service.get_world()
    assert handle.observe_idle(shifted(initial, -1.0))
    assert service.get_world()["command_revision"] == before["command_revision"]
    write = {"kind": "write", "args": {"object_id": "note", "text": "New"}}
    item = submit_command(service, "unreachable", before["command_revision"], action=write)
    assert item["error"]["code"] == "invalid_action"
    assert "reach" in item["error"]["message"]
    assert service.get_world()["objects"]["note"]["text"] == "Original"


def test_busy_and_foreground_observations_remain_command_changes(command_body):
    service, handle, clock, initial = command_body
    before = service.get_world()
    assert submit_command(service, "move", before["command_revision"])["status"] == "accepted"
    assert submit_command(service, "busy", before["command_revision"])["error"]["code"] == "busy"
    assert handle.claim_next()["request_id"] == "move"
    clock.advance(0.1)
    assert handle.feedback("move", 0, "running", observation=shifted(initial, 0.01))
    current = service.get_world()
    assert current["command_revision"] == before["command_revision"] + 1
    assert current["idle_pose_updates"] == before["idle_pose_updates"]


def test_command_replay_stays_idempotent_after_new_body_revision(command_body):
    service, handle, _, initial = command_body
    revision = service.get_world()["command_revision"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        items = list(pool.map(lambda _: submit_command(service, "move", revision), range(2)))
    assert sum(not item["replayed"] for item in items) == 1
    assert handle.claim_next()["request_id"] == "move"
    assert handle.feedback("move", 0, "running")
    assert handle.feedback("move", 1, "completed", observation=shifted(initial, 1.0))
    events = service.events()
    replay = submit_command(service, "move", revision)
    assert replay["replayed"] and replay["status"] == "completed"
    assert replay["validated_revision"] == items[0]["validated_revision"]
    assert service.events() == events
    with pytest.raises(ActionError, match="different envelope"):
        submit_command(service, "move", service.get_world()["command_revision"])
    with pytest.raises(ActionError, match="different envelope"):
        service.submit("move", revision, MOVE)


def test_idle_counter_and_pose_rollback_and_restart_together(command_body):
    service, handle, clock, initial = command_body
    before = service.get_world()
    raw_before = service.runtime.snapshot()
    with service.runtime.connection() as conn:
        conn.execute(
            "CREATE TRIGGER fail_pose BEFORE UPDATE ON world "
            "BEGIN SELECT RAISE(ABORT, 'pose rollback'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="pose rollback"):
        handle.observe_idle(shifted(initial, 0.01))
    assert service.runtime.snapshot() == raw_before
    assert service.get_world() == before
    with service.runtime.connection() as conn:
        conn.execute("DROP TRIGGER fail_pose")
    assert handle.observe_idle(shifted(initial, 0.01))
    reopened = ExecutionService(Runtime(service.runtime.path, create=False), clock=clock)
    assert reopened.get_world() == service.get_world()
    assert reopened.get_world()["command_revision"] == before["command_revision"]
    assert "command_revision" not in reopened.runtime.snapshot()
    item = submit_command(reopened, "after-restart", before["command_revision"])
    assert item["status"] == "accepted"


@pytest.mark.parametrize("counter", [-1, True, 0.5, "0", "greater-than-revision"])
def test_corrupt_idle_counter_cannot_admit_an_action_or_new_pose(command_body, counter):
    service, handle, _, initial = command_body
    corrupted = service.runtime.snapshot()
    corrupted["idle_pose_updates"] = (
        corrupted["revision"] + 1 if counter == "greater-than-revision" else counter
    )
    with service.runtime.connection() as conn:
        conn.execute("UPDATE world SET data=? WHERE id=1", (encode(corrupted),))
    with pytest.raises(ActionError, match="revision counters"):
        service.get_world()
    with pytest.raises(ActionError, match="revision counters"):
        service.submit("invalid-world", corrupted["revision"], MOVE)
    with pytest.raises(ActionError, match="revision counters"):
        handle.observe_idle(shifted(initial, 0.01))
    assert service.runtime.snapshot() == corrupted
    assert service.events() == []
