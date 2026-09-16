"""B04 transaction and intervention tests; analytic poses, no live avatar claim."""

import copy
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from conftest import Clock
from test_appearance_checkpoint import observed

from promethee.appearance_checkpoint import pose_digest
from promethee.execution import ExecutionService, command_revision
from promethee.object_actions import IDENTITY
from promethee.pet_world import GRAB_SECONDS, PetWorld
from promethee.runtime import Runtime
from promethee.spatial import attachment_transform
from promethee.world import ActionError, validate_observation

pytest.importorskip("numpy")  # Optional avatar geometry, exercised in the CI extras job.


@pytest.fixture
def pet(tmp_path, articulated_pose):
    clock = Clock()
    runtime = Runtime(tmp_path / "pet.sqlite3", data_origin="session", session_kind="interactive")
    service = ExecutionService(runtime, clock=clock)
    handle = service.acquire_controller(
        source="kinematic", supported_actions=["move", "posture"], lease_seconds=300
    )
    observation = observed(articulated_pose)
    assert handle.reconcile(observation, stopped=True)
    world, stop = PetWorld(service, handle), Mock()
    world.suspend(observation, stop, False)
    return SimpleNamespace(
        world=world,
        service=service,
        handle=handle,
        observation=observation,
        clock=clock,
        stop=stop,
    )


def envelope(pet, kind, args, rid="input-1", revision=None):
    return {
        "request_id": rid,
        "expected_command_revision": (
            command_revision(pet.service.runtime.snapshot()) if revision is None else revision
        ),
        "action": {"kind": kind, "args": args},
    }


def intervene(pet, kind, args, rid="input-1"):
    result = pet.world.apply(envelope(pet, kind, args, rid), pet.observation, pet.stop)
    pet.observation = copy.deepcopy(result["observation"])
    return result


def spawn(pet, *, position=None, model="ball", rid="spawn"):
    return intervene(pet, "spawn", {"model": model, "position": position or [1.5, 1, 0]}, rid)[
        "object_id"
    ]


def tick(pet, dt=0.05, **kwargs):
    pet.observation, state = pet.world.physics(pet.observation, dt, **kwargs)
    return state


@pytest.mark.parametrize("session_kind", [None, "qualification"])
def test_pet_checkpoint_requires_an_interactive_world(tmp_path, articulated_pose, session_kind):
    service = ExecutionService(
        Runtime(tmp_path / "not-pet.sqlite3", data_origin="session", session_kind=session_kind),
        clock=Clock(),
    )
    handle = service.acquire_controller(source="kinematic", supported_actions=["move"])
    assert handle.reconcile(observed(articulated_pose), stopped=True)
    before = service.runtime.snapshot()
    with pytest.raises(ActionError, match="interactive"):
        PetWorld(service, handle)
    assert service.runtime.snapshot() == before


def test_spawn_replay_returns_original_result_without_stop_or_second_object(pet):
    request = envelope(pet, "spawn", {"model": "ball", "position": [1, 1, 0]})
    original = copy.deepcopy(pet.observation)
    result = pet.world.apply(request, pet.observation, pet.stop)
    pet.observation = result["observation"]
    assert original["objects"] == {}
    before, events = pet.service.runtime.snapshot(), pet.service.events()
    replay = pet.world.apply(request, pet.observation, pet.stop)
    assert replay == {**result, "replayed": True}
    assert pet.service.runtime.snapshot() == before
    assert pet.service.events() == events
    assert len(before["objects"]) == 1
    assert pet.stop.call_count == 1
    event = events[-1]
    assert event["actor"] == "user" and event["kind"] == "external_intervention"
    assert event["envelope"] == request
    assert result["command_revision"] == command_revision(before)


def test_request_id_conflict_and_stale_revision_are_rejected_before_stop(pet):
    request = envelope(pet, "spawn", {"model": "ball", "position": [1, 1, 0]})
    pet.observation = pet.world.apply(request, pet.observation, pet.stop)["observation"]
    before, events, stops = (
        pet.service.runtime.snapshot(),
        pet.service.events(),
        pet.stop.call_count,
    )
    conflict = copy.deepcopy(request)
    conflict["action"]["args"]["position"] = [2, 1, 0]
    with pytest.raises(ActionError, match="Request ID"):
        pet.world.apply(conflict, pet.observation, pet.stop)
    stale = envelope(pet, "relocate_avatar", {"position": [0.5, 0]}, "stale", revision=0)
    with pytest.raises(ActionError, match="revision_conflict"):
        pet.world.apply(stale, pet.observation, pet.stop)
    assert pet.stop.call_count == stops
    assert pet.service.runtime.snapshot() == before
    assert pet.service.events() == events


@pytest.mark.parametrize(
    "kind,args",
    [
        ("spawn", {"model": "ball", "position": [1, 0, 0]}),
        ("spawn", {"model": "ball", "position": [0, 1, 0]}),
        ("spawn", {"model": "unknown", "position": [1, 1, 0]}),
        ("grab_begin", {"target": "object", "object_id": "missing"}),
        ("grab_begin", {"target": "avatar", "object_id": "missing"}),
        ("relocate_avatar", {"position": [4.3, 0]}),
        ("throw", {"object_id": "missing", "velocity": [1, 0, 0]}),
    ],
)
def test_invalid_interventions_preserve_world_events_and_running_playback(pet, kind, args):
    before, events = pet.service.runtime.snapshot(), pet.service.events()
    with pytest.raises(ActionError):
        pet.world.apply(envelope(pet, kind, args), pet.observation, pet.stop)
    pet.stop.assert_not_called()
    assert pet.service.runtime.snapshot() == before
    assert pet.service.events() == events


def test_grab_begin_freezes_position_and_second_pointer_cannot_end_or_replace_it(pet):
    initial = copy.deepcopy(pet.observation)
    begun = intervene(pet, "grab_begin", {"target": "avatar"}, "pointer-one")
    assert begun["grab_id"] == "pointer-one"
    assert pet.observation == initial
    before, stops = pet.service.runtime.snapshot(), pet.stop.call_count
    for kind, args in (
        ("grab_begin", {"target": "avatar"}),
        ("grab_end", {"grab_id": "pointer-two", "position": [1, 1]}),
        ("grab_cancel", {"grab_id": "pointer-two"}),
    ):
        with pytest.raises(ActionError):
            pet.world.apply(envelope(pet, kind, args, "foreign-" + kind), pet.observation, pet.stop)
    assert pet.stop.call_count == stops
    assert pet.service.runtime.snapshot() == before
    assert tick(pet)["grab"]["grab_id"] == "pointer-one"


def test_grab_completion_uses_its_lease_even_when_begin_revision_has_changed(pet):
    original_revision = command_revision(pet.service.runtime.snapshot())
    intervene(pet, "grab_begin", {"target": "avatar"}, "begin")
    completed = envelope(
        pet, "grab_end", {"grab_id": "begin", "position": [0.7, -0.4]}, "end", original_revision
    )
    result = pet.world.apply(completed, pet.observation, pet.stop)
    pet.observation = result["observation"]
    assert result["observation"]["avatar"]["position"] == [0.7, -0.4]
    assert pet.service.runtime.snapshot()["sandbox"]["grab"] is None
    before, stops = pet.service.runtime.snapshot(), pet.stop.call_count
    replay = pet.world.apply(completed, pet.observation, pet.stop)
    assert replay["replayed"]
    assert pet.service.runtime.snapshot() == before
    assert pet.stop.call_count == stops


def test_invalid_grab_end_keeps_the_lease_and_cancel_preserves_observation(pet):
    initial = copy.deepcopy(pet.observation)
    intervene(pet, "grab_begin", {"target": "avatar"}, "begin")
    before = pet.service.runtime.snapshot()
    with pytest.raises(ActionError):
        intervene(pet, "grab_end", {"grab_id": "begin", "position": [9, 0]}, "invalid-end")
    assert pet.service.runtime.snapshot() == before
    assert pet.stop.call_count == 1
    intervene(pet, "grab_cancel", {"grab_id": "begin"}, "cancel")
    assert pet.observation == initial
    assert pet.service.runtime.snapshot()["sandbox"]["grab"] is None


def test_grab_expiry_releases_once_without_applying_late_pointer_position(pet):
    initial = copy.deepcopy(pet.observation)
    intervene(pet, "grab_begin", {"target": "avatar"}, "begin")
    pet.clock.advance(GRAB_SECONDS)
    with pytest.raises(ActionError, match="expired"):
        intervene(pet, "grab_end", {"grab_id": "begin", "position": [1, 1]}, "too-late")
    assert tick(pet, simulate=False)["grab"] is None
    tick(pet, simulate=False)
    assert pet.observation == initial
    released = [e for e in pet.service.events() if e["kind"] == "grab_released"]
    assert len(released) == 1 and released[0]["reason"] == "pointer_timeout"


def test_restart_releases_grab_and_fences_the_previous_controller(pet):
    intervene(pet, "grab_begin", {"target": "avatar"}, "begin")
    old_world = pet.world
    assert pet.handle.release()
    reopened = ExecutionService(Runtime(pet.service.runtime.path), clock=pet.clock)
    replacement = reopened.acquire_controller(source="kinematic", supported_actions=["move"])
    assert replacement.reconcile(pet.observation, stopped=True)
    PetWorld(reopened, replacement)
    assert reopened.runtime.snapshot()["sandbox"]["grab"] is None
    assert reopened.events()[-1]["reason"] == "controller_restart"
    before = reopened.runtime.snapshot()
    with pytest.raises(ActionError, match="owns"):
        old_world.apply(
            envelope(pet, "relocate_avatar", {"position": [1, 1]}), pet.observation, pet.stop
        )
    assert reopened.runtime.snapshot() == before
    assert pet.stop.call_count == 1


def test_avatar_relocation_moves_pose_and_held_object_with_same_visible_checkpoint(pet):
    pet.observation["pose"]["positions"][10] = [0.5, 1, 0]
    pet.observation = observed(pet.observation["pose"])
    pet.observation["appearance"]["aligned_hands"] = ["RightHand"]
    attachment = {"joint": "RightHand", "position": [0.2, 0, 0], "rotation": IDENTITY}
    transform = attachment_transform(attachment, pet.observation["pose"])
    pet.observation["objects"]["held"] = {
        "asset": "ball",
        "position": [0.7, 0],
        "spatial": {**transform, "attachment": attachment},
    }
    pet.observation["avatar"]["holding"] = "held"
    assert pet.handle.reconcile(pet.observation, stopped=True)
    before = copy.deepcopy(pet.observation)
    intervene(pet, "relocate_avatar", {"position": [1, -0.5]})
    result = pet.observation
    for old, new in zip(before["pose"]["positions"], result["pose"]["positions"], strict=True):
        assert new == pytest.approx([old[0] + 1, old[1], old[2] - 0.5])
    assert result["pose"]["rotations"] == before["pose"]["rotations"]
    assert result["appearance"]["frame"] == before["appearance"]["frame"]
    assert result["appearance"]["core_pose_sha256"] == pose_digest(result["pose"])
    assert result["appearance"]["core_pose_sha256"] != before["appearance"]["core_pose_sha256"]
    assert result["objects"]["held"]["spatial"]["position"] == pytest.approx([1.7, 1, -0.5])
    assert result["objects"]["held"]["spatial"]["attachment"] == attachment
    assert validate_observation(result) == result
    snapshot = pet.service.runtime.snapshot()
    assert {key: snapshot[key] for key in result} == result
    with pytest.raises(ActionError, match="held"):
        intervene(pet, "relocate_object", {"object_id": "held", "position": [2, 1, 0]}, "detach")


def test_external_input_interrupts_existing_action_without_reporting_it_completed(pet):
    request = pet.service.submit(
        "walking",
        pet.service.get_world()["revision"],
        {"kind": "move", "args": {"position": [1, 0]}},
    )
    assert request["status"] == "accepted"
    assert pet.handle.claim_next()["request_id"] == "walking"
    assert pet.handle.feedback("walking", 0, "running", observation=pet.observation)
    intervene(pet, "relocate_avatar", {"position": [-0.4, 0.2]})
    assert pet.service.get("walking")["status"] == "interrupted"
    assert pet.service.get("walking")["error"]["code"] == "external_intervention"
    assert not pet.handle.feedback(
        "walking", 1, "completed", observation=observed(pet.observation["pose"])
    )
    assert pet.service.runtime.snapshot()["avatar"]["position"] == [-0.4, 0.2]


def test_object_drop_with_throw_persists_and_pause_does_not_advance_flight(pet):
    oid = spawn(pet)
    intervene(pet, "grab_begin", {"target": "object", "object_id": oid}, "begin")
    intervene(
        pet,
        "grab_end",
        {
            "grab_id": "begin",
            "position": [1.5, 1.2, 0],
            "velocity": [1, 2, 0],
        },
        "release",
    )
    before = copy.deepcopy(pet.observation)
    checkpoint = copy.deepcopy(pet.service.runtime.snapshot()["sandbox"])
    assert tick(pet, simulate=False) == checkpoint
    assert pet.observation == before
    state = tick(pet)
    assert oid in state["flights"]
    assert pet.observation["objects"][oid]["spatial"]["position"][0] > 1.5
    assert pet.handle.release()
    reopened = ExecutionService(Runtime(pet.service.runtime.path), clock=pet.clock)
    saved = reopened.runtime.snapshot()
    assert saved["sandbox"]["flights"] == state["flights"]
    assert saved["objects"] == pet.observation["objects"]
    replacement = reopened.acquire_controller(source="kinematic", supported_actions=["move"])
    assert replacement.reconcile(pet.observation, stopped=True)
    restarted = PetWorld(reopened, replacement)
    assert reopened.runtime.snapshot()["sandbox"]["suspended"]
    restarted.suspend(pet.observation, pet.stop, False)
    expected, expected_state = pet.observation, state
    advanced, advanced_state = restarted.physics(expected, 0.05)
    assert advanced != expected
    assert (
        advanced_state["flights"][oid]["velocity"][1]
        < expected_state["flights"][oid]["velocity"][1]
    )


def test_throw_reports_contact_once_and_rest_from_simulated_outcome(pet):
    oid = spawn(pet)
    intervene(pet, "throw", {"object_id": oid, "velocity": [0, -2, 0]}, "throw")
    state = pet.service.runtime.snapshot()["sandbox"]
    for _ in range(300):
        state = tick(pet)
        if not state["flights"]:
            break
    assert state["flights"] == {}
    assert pet.observation["objects"][oid]["spatial"]["position"][1] == 0.06
    events = pet.service.events()
    contacts = [e for e in events if e["kind"] == "object_contact"]
    rests = [e for e in events if e["kind"] == "object_rest"]
    assert len(contacts) == 1 and contacts[0]["contacts"] == ["floor"]
    assert len(rests) == 1 and rests[0]["object_id"] == oid
    assert all(e["actor"] == "simulation" for e in contacts + rests)
    before = pet.service.runtime.snapshot()
    tick(pet)
    assert pet.service.runtime.snapshot() == before
    assert pet.service.events() == events


@pytest.mark.parametrize(
    "position,velocity", [([4.35, 1, 0], [4, 0, 0]), ([1.5, 4.75, 0], [0, 4, 0])]
)
def test_physics_can_reach_its_walls_without_using_stricter_drag_bounds(pet, position, velocity):
    oid = spawn(pet, position=position)
    intervene(pet, "throw", {"object_id": oid, "velocity": velocity}, "throw")
    tick(pet, 0.02)
    for _ in range(15):
        tick(pet, 0.02)
    assert any(
        e["kind"] == "object_contact" and "wall" in e["contacts"] for e in pet.service.events()
    )


def test_grabbing_a_flying_object_interrupts_only_that_flight(pet):
    first = spawn(pet, position=[1, 1, 0], rid="first")
    second = spawn(pet, position=[2, 1, 0], rid="second")
    intervene(pet, "throw", {"object_id": first, "velocity": [2, 1, 0]}, "throw-first")
    intervene(pet, "throw", {"object_id": second, "velocity": [0, 1, 0]}, "throw-second")
    intervene(pet, "grab_begin", {"target": "object", "object_id": first}, "begin")
    state = pet.service.runtime.snapshot()["sandbox"]
    assert first not in state["flights"] and second in state["flights"]
    initial = copy.deepcopy(pet.observation)
    tick(pet)
    assert pet.observation == initial
    intervene(pet, "grab_cancel", {"grab_id": "begin"}, "cancel")
    resumed = tick(pet)
    assert resumed["flights"][first]["velocity"][0] == 0
    assert resumed["flights"][first]["velocity"][1] < 0
    assert pet.observation["objects"][first]["position"] == initial["objects"][first]["position"]
    assert pet.observation["objects"][second] != initial["objects"][second]


def test_suspension_preserves_flight_and_releases_pointer_without_replaying(pet):
    oid = spawn(pet)
    intervene(pet, "throw", {"object_id": oid, "velocity": [0, 2, 0]}, "throw")
    intervene(pet, "grab_begin", {"target": "avatar"}, "begin")
    pet.world.suspend(pet.observation, pet.stop, True)
    suspended = pet.service.runtime.snapshot()
    assert suspended["sandbox"]["suspended"]
    assert suspended["sandbox"]["grab"] is None
    before = copy.deepcopy(pet.observation)
    tick(pet, 0.25)
    assert pet.observation == before
    assert pet.service.runtime.snapshot() == suspended
    stops = pet.stop.call_count
    pet.world.suspend(pet.observation, pet.stop, True)
    assert pet.stop.call_count == stops
    pet.world.suspend(pet.observation, pet.stop, False)
    assert pet.stop.call_count == stops
    tick(pet)
    assert pet.observation["objects"][oid]["spatial"]["position"][1] > 1


def test_invalid_throw_does_not_cancel_the_existing_motion(pet):
    oid = spawn(pet)
    intervene(pet, "throw", {"object_id": oid, "velocity": [0, 2, 0]}, "first-throw")
    before, stops = pet.service.runtime.snapshot(), pet.stop.call_count
    with pytest.raises(ActionError):
        intervene(pet, "throw", {"object_id": oid, "velocity": [10, 10, 0]}, "too-fast")
    assert pet.service.runtime.snapshot() == before
    assert pet.stop.call_count == stops


def test_contact_event_failure_rolls_back_the_physics_checkpoint(pet):
    oid = spawn(pet, position=[1.5, 0.07, 0])
    intervene(pet, "throw", {"object_id": oid, "velocity": [0, -2, 0]}, "throw")
    before, events = pet.service.runtime.snapshot(), pet.service.events()
    observation = copy.deepcopy(pet.observation)
    with pet.service.runtime.connection() as conn:
        conn.execute(
            "CREATE TRIGGER reject_contact BEFORE INSERT ON execution_events "
            "BEGIN SELECT RAISE(ABORT, 'contact rollback'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="contact rollback"):
        tick(pet)
    assert pet.service.runtime.snapshot() == before
    assert pet.service.events() == events
    assert pet.observation == observation


def test_sql_failure_rolls_back_observation_event_and_request_together(pet):
    before, events = pet.service.runtime.snapshot(), pet.service.events()
    request = envelope(pet, "spawn", {"model": "ball", "position": [1, 1, 0]})
    with pet.service.runtime.connection() as conn:
        conn.execute(
            "CREATE TRIGGER reject_pet BEFORE INSERT ON execution_events "
            "BEGIN SELECT RAISE(ABORT, 'pet rollback'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="pet rollback"):
        pet.world.apply(request, pet.observation, pet.stop)
    assert pet.service.runtime.snapshot() == before
    assert pet.service.events() == events
    with pet.service.runtime.connection() as conn:
        conn.execute("DROP TRIGGER reject_pet")
    result = pet.world.apply(request, pet.observation, pet.stop)
    assert not result["replayed"]
    assert len(result["observation"]["objects"]) == 1


def test_unsupported_checkpoint_is_rejected_without_modification(pet):
    with pet.service.runtime.connection() as conn:
        world = pet.service.runtime.snapshot()
        world["sandbox"]["version"] = 9
        conn.execute("UPDATE world SET data=? WHERE id=1", (json.dumps(world),))
    before = pet.service.runtime.snapshot()
    with pytest.raises(ActionError, match="version"):
        PetWorld(pet.service, pet.handle)
    assert pet.service.runtime.snapshot() == before


@pytest.mark.parametrize("model,height", [("ball", 0.0599999999999999), ("plush", 0.1085)])
def test_palette_floor_height_accepts_geometry_and_ray_rounding(pet, model, height):
    oid = spawn(pet, model=model, position=[1.5, height, 0])
    assert pet.observation["objects"][oid]["spatial"]["position"][1] == pytest.approx(height)


def test_exported_external_events_preserve_author_and_manual_edits(pet, tmp_path):
    from promethee.journal import export_journal

    spawn(pet)
    vault = tmp_path / "vault"
    assert export_journal(pet.service.runtime, vault) == 1
    note = next(vault.rglob("environment-*.md"))
    text = note.read_text(encoding="utf-8")
    assert "source: promethee-sandbox" in text and '"actor": "user"' in text
    note.write_text(text + "\nManual annotation retained.\n", encoding="utf-8")
    assert export_journal(pet.service.runtime, vault) == 0
    assert note.read_text(encoding="utf-8").endswith("Manual annotation retained.\n")
