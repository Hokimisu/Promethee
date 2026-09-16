"""Rigid-transform and persistence fixtures; no physical grasp is simulated."""

import copy
import json
import sqlite3

import pytest

from promethee.execution import ExecutionService
from promethee.migrations import migrate
from promethee.runtime import Runtime
from promethee.spatial import attachment_transform, follow_attachment
from promethee.world import ActionError, validate_observation

IDENTITY = [[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]]
TURN = [[0.0, 0, 1], [0, 1.0, 0], [-1.0, 0, 0]]


@pytest.fixture
def held(articulated_pose):
    pose = copy.deepcopy(articulated_pose)
    pose["positions"][10] = [0.3, 1.1, 0.2]
    pose["rotations"][10] = copy.deepcopy(TURN)
    attachment = {"joint": "RightHand", "position": [0.08, 0, 0], "rotation": IDENTITY}
    transform = attachment_transform(attachment, pose)
    obj = {
        "asset": "plush",
        "position": [0.3, 0.12],
        "spatial": {**transform, "attachment": attachment},
    }
    return {
        "avatar": {"position": [0.0, 0.0], "holding": "item", "seated_on": None},
        "objects": {"item": obj},
        "pose": pose,
    }


def test_hand_attachment_uses_rotated_local_offset_and_preserves_input(held):
    before = copy.deepcopy(held)
    assert validate_observation(held) == held
    pose = copy.deepcopy(held["pose"])
    pose["positions"][10] = [1.0, 1.2, 0.5]
    pose["rotations"][10] = copy.deepcopy(IDENTITY)
    obj = follow_attachment(held["objects"]["item"], pose)
    assert obj["position"] == [1.08, 0.5]
    assert obj["spatial"]["position"] == [1.08, 1.2, 0.5]
    assert obj["spatial"]["rotation"] == IDENTITY
    assert held == before
    updated = {**held, "pose": pose, "objects": {"item": obj}}
    assert validate_observation(updated) == updated


@pytest.mark.parametrize(
    "invalid",
    [
        "position",
        "rotation",
        "floor",
        "missing-pose",
        "missing-held",
        "missing-attachment",
        "wrong-hand",
        "reflection",
        "nan",
        "extra-object",
    ],
)
def test_inconsistent_spatial_observations_are_refused(held, invalid):
    spatial = held["objects"]["item"]["spatial"]
    if invalid == "position":
        spatial["position"][1] += 0.02
    elif invalid == "rotation":
        spatial["rotation"] = copy.deepcopy(IDENTITY)
    elif invalid == "floor":
        held["objects"]["item"]["position"][0] += 0.1
    elif invalid == "missing-pose":
        held["pose"] = None
    elif invalid == "missing-held":
        held["avatar"]["holding"] = None
    elif invalid == "missing-attachment":
        spatial["attachment"] = None
    elif invalid == "wrong-hand":
        spatial["attachment"]["joint"] = "Hips"
    elif invalid == "reflection":
        spatial["rotation"] = [[-1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]]
    elif invalid == "nan":
        spatial["attachment"]["position"][0] = float("nan")
    else:
        held["objects"]["second"] = copy.deepcopy(held["objects"]["item"])
    with pytest.raises(ActionError):
        validate_observation(held)


def test_releasing_attachment_keeps_observed_pose(held):
    held["avatar"]["holding"] = None
    held["objects"]["item"]["spatial"]["attachment"] = None
    assert validate_observation(held) == held
    with pytest.raises(ValueError, match="attachment requires"):
        follow_attachment(held["objects"]["item"], held["pose"])


def test_spatial_fixture_cannot_fall_back_to_instant_logical_actions(tmp_path, held):
    runtime = Runtime(tmp_path / "fixture.sqlite3")
    service = ExecutionService(runtime)
    handle = service.acquire_controller(source="logical-test", supported_actions=["move"])
    handle.reconcile(held, stopped=True)
    handle.release()
    before = runtime.snapshot()
    with pytest.raises(ActionError, match="Spatial objects"):
        runtime.execute("shortcut", {"kind": "move", "args": {"position": [1, 0]}})
    assert runtime.snapshot() == before


@pytest.mark.parametrize("crash", [False, True])
def test_progress_interruption_and_restart_preserve_actual_hand_object_transform(
    tmp_path, held, crash
):
    now = [100.0]
    path = tmp_path / "world.sqlite3"
    service = ExecutionService(Runtime(path, data_origin="session"), clock=lambda: now[0])
    handle = service.acquire_controller(source="kinematic", supported_actions=["move"])
    assert handle.reconcile(held, stopped=True)
    revision = service.get_world()["revision"]
    action = {"kind": "move", "args": {"position": [1, 0]}}
    assert service.submit("carry", revision, action)["status"] == "accepted"
    handle.claim_next()
    handle.feedback("carry", 0, "running")
    moved = copy.deepcopy(held)
    moved["avatar"]["position"] = [0.4, 0]
    for point in moved["pose"]["positions"]:
        point[0] += 0.4
    moved["objects"]["item"] = follow_attachment(held["objects"]["item"], moved["pose"])
    assert handle.feedback("carry", 1, "running", observation=moved)
    assert service.get_world()["objects"] == moved["objects"]
    before = service.get_world(), service.events()
    with service.runtime.connection() as conn:
        conn.execute(
            "CREATE TRIGGER fail_spatial_event BEFORE INSERT ON execution_events "
            "BEGIN SELECT RAISE(ABORT, 'spatial rollback'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="spatial rollback"):
        handle.feedback("carry", 2, "running", observation=held)
    assert (service.get_world(), service.events()) == before
    with service.runtime.connection() as conn:
        conn.execute("DROP TRIGGER fail_spatial_event")
    wrong = copy.deepcopy(moved)
    wrong["objects"]["item"]["spatial"]["position"][1] += 0.1
    with pytest.raises(ActionError):
        handle.feedback("carry", 2, "running", observation=wrong)
    assert (service.get_world(), service.events()) == before
    if crash:
        now[0] += 6
        assert service.get("carry")["status"] == "interrupted"
    else:
        service.cancel("carry")
        assert handle.claim_cancellation()["request_id"] == "carry"
        assert handle.feedback("carry", 2, "cancelled", observation=moved)
        handle.release()
    restarted = ExecutionService(Runtime(path), clock=lambda: now[0])
    assert restarted.get_world()["objects"] == moved["objects"]
    second = restarted.acquire_controller(source="kinematic", supported_actions=["move"])
    assert second.reconcile(moved, stopped=True)
    assert not handle.feedback("carry", 3, "completed", observation=held)
    assert restarted.submit("carry", revision, action)["replayed"]
    assert second.claim_next() is None
    assert restarted.get_world()["objects"] == moved["objects"]


@pytest.mark.parametrize("fail", [False, True])
def test_v8_migration_preserves_logical_objects_without_inventing_spatial_data(tmp_path, fail):
    path, backup = tmp_path / "world.sqlite3", tmp_path / "backup.sqlite3"
    runtime = Runtime(path)
    runtime.execute(
        "spawn",
        {"kind": "spawn", "args": {"object_id": "old", "asset": "plush", "position": [0, 0]}},
    )
    with runtime.connection() as conn:
        old = runtime.snapshot()
        old["schema_version"] = 8
        old.pop("appearance")
        old.pop("idle_pose_updates")
        conn.execute("UPDATE world SET data=?", (json.dumps(old),))
        if fail:
            conn.execute(
                "CREATE TRIGGER fail_upgrade BEFORE UPDATE ON world "
                "BEGIN SELECT RAISE(ABORT, 'rollback'); END"
            )
    with pytest.raises(ValueError, match="migration|migrate"):
        Runtime(path)
    if fail:
        with pytest.raises(sqlite3.IntegrityError, match="rollback"):
            migrate(path, backup)
        with sqlite3.connect(path) as conn:
            assert json.loads(conn.execute("SELECT data FROM world").fetchone()[0]) == old
    else:
        assert migrate(path, backup)["schema_version"] == 12
        assert Runtime(path).snapshot() == {
            **old,
            "schema_version": 12,
            "appearance": None,
            "idle_pose_updates": 0,
        }
    with sqlite3.connect(backup) as conn:
        assert json.loads(conn.execute("SELECT data FROM world").fetchone()[0]) == old
