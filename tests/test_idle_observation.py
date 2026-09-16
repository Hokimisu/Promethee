"""CPU authority/storage checks; synthetic poses do not qualify motor quality."""

import copy

import pytest
from conftest import Clock
from test_appearance_checkpoint import observed

from promethee.execution import ExecutionService, timestamp
from promethee.runtime import Runtime
from promethee.world import ActionError


@pytest.fixture
def idle_body(tmp_path, articulated_pose):
    clock = Clock()
    service = ExecutionService(
        Runtime(tmp_path / "world.sqlite3", data_origin="session", session_kind="qualification"),
        clock=clock,
    )
    handle = service.acquire_controller(source="kinematic", supported_actions=["move"])
    initial = observed(articulated_pose)
    assert handle.reconcile(initial, stopped=True)
    pose = copy.deepcopy(articulated_pose)
    for point in pose["positions"]:
        point[0] += 0.01
    return service, handle, clock, initial, observed(pose)


def test_idle_observation_persists_body_and_appearance_without_an_execution(idle_body):
    service, handle, clock, _, candidate = idle_body
    before = service.get_world()
    clock.advance(0.25)
    assert handle.observe_idle(candidate)
    world = service.get_world()
    assert {key: world[key] for key in candidate} == candidate
    assert world["revision"] == before["revision"] + 1
    assert world["body"] == {
        "status": "confirmed",
        "source": "kinematic",
        "observed_at": timestamp(clock()),
    }
    assert service.events() == []
    with service.runtime.connection() as conn:
        for table in ("executions", "commands", "activities"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    reopened = Runtime(service.runtime.path, create=False).snapshot()
    assert reopened == world
    candidate["pose"]["positions"][0][0] = 999
    assert service.get_world() == world


@pytest.mark.parametrize("phase", ["accepted", "running", "cancel_requested"])
def test_idle_observation_yields_to_durable_execution_before_claim(idle_body, phase):
    service, handle, _, initial, candidate = idle_body
    item = service.submit(
        "move", service.get_world()["revision"], {"kind": "move", "args": {"position": [1, 0]}}
    )
    assert item["status"] == "accepted"
    if phase != "accepted":
        assert handle.claim_next()["request_id"] == "move"
        assert handle.feedback("move", 0, "running", observation=initial)
    if phase == "cancel_requested":
        service.cancel("move")
    before, events, execution = service.get_world(), service.events(), service.get("move")
    with pytest.raises(ActionError, match="execution is active"):
        handle.observe_idle(candidate)
    assert service.get_world() == before
    assert service.events() == events
    assert service.get("move") == execution


def test_idle_can_resume_after_confirmed_cancellation(idle_body):
    service, handle, _, initial, candidate = idle_body
    service.submit(
        "move", service.get_world()["revision"], {"kind": "move", "args": {"position": [1, 0]}}
    )
    handle.claim_next()
    handle.feedback("move", 0, "running", observation=initial)
    service.cancel("move")
    handle.claim_cancellation()
    assert handle.feedback("move", 1, "cancelled", observation=initial)
    events = service.events()
    assert handle.observe_idle(candidate)
    assert service.events() == events
    assert service.get("move")["observation"] == initial


def test_idle_observation_does_not_renew_or_outlive_lease(idle_body):
    service, handle, clock, _, candidate = idle_body
    clock.advance(4.9)
    assert handle.observe_idle(candidate)
    clock.advance(0.1)
    later = copy.deepcopy(candidate)
    later["appearance"]["frame"]["root_y_offset"] += 0.001
    assert handle.observe_idle(later) is False
    world = service.get_world()
    assert {key: world[key] for key in candidate} == candidate
    assert world["body"]["status"] == "unconfirmed"
    assert service.events() == []


def test_replaced_controller_cannot_publish_idle_observations(idle_body):
    service, old, _, initial, candidate = idle_body
    assert old.release()
    replacement = service.acquire_controller(source="kinematic", supported_actions=["move"])
    assert replacement.observe_idle(initial)
    before = service.get_world()
    assert old.observe_idle(candidate) is False
    assert service.get_world() == before
    assert replacement.observe_idle(candidate)


@pytest.mark.parametrize("defect", ["pose", "appearance", "missing_appearance", "root", "nan"])
def test_invalid_idle_observation_cannot_change_the_world(idle_body, defect):
    service, handle, _, _, candidate = idle_body
    before = service.get_world()
    if defect == "pose":
        candidate["pose"] = None
    elif defect == "appearance":
        candidate["appearance"]["pose_sha256"] = "0" * 64
    elif defect == "missing_appearance":
        del candidate["appearance"]
    elif defect == "root":
        candidate["avatar"]["position"][0] += 1
    else:
        candidate["pose"]["positions"][0][0] = float("nan")
    with pytest.raises(ActionError):
        handle.observe_idle(candidate)
    assert service.get_world() == before
    assert service.events() == []


def test_idle_observation_is_invisible_until_commit_and_rolls_back(idle_body, monkeypatch):
    service, handle, _, _, candidate = idle_body
    before = service.get_world()
    original = service._observe

    def write_then_fail(conn, observation, source, now):
        original(conn, observation, source, now)
        # A separate connection still sees the previous coherent checkpoint.
        assert service.runtime.snapshot() == before
        raise RuntimeError("injected failure after observation write")

    monkeypatch.setattr(service, "_observe", write_then_fail)
    with pytest.raises(RuntimeError, match="injected failure"):
        handle.observe_idle(candidate)
    assert service.get_world() == before
    assert service.events() == []
