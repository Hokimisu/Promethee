"""Synthetic CPU orchestration; real ARDY quality is assessed separately."""

import copy
import sqlite3

import pytest
from pet_body import PetController
from test_presence import MotionWorker, Preparation

from promethee.appearance_checkpoint import pose_digest
from promethee.execution import ExecutionService
from promethee.kinematic import MAX_MOTION_ATTEMPTS, RETRYABLE_MOTION_ERRORS, UNSUPPORTED_PHASE
from promethee.object_actions import IDENTITY
from promethee.runtime import Runtime


@pytest.fixture
def pet_driver(tmp_path):
    now = [1000.0]
    service = ExecutionService(
        Runtime(tmp_path / "world.sqlite3", data_origin="session", session_kind="interactive"),
        clock=lambda: now[0],
    )
    worker, prep = MotionWorker(tmp_path), Preparation()
    controller = PetController(
        service, worker, clock=lambda: now[0], continuous_motion=True, appearance_preparation=prep
    )
    controller.tick()
    worker.finish()
    controller.tick()
    prep.finish()
    controller.tick()
    assert controller.ready
    controller.set_viewing(True)
    yield controller, service, worker, prep, now
    controller.close()


def intervene(c, service, rid, kind, **args):
    return c.intervene(
        {
            "request_id": rid,
            "expected_command_revision": service.get_world()["command_revision"],
            "action": {"kind": kind, "args": args},
        }
    )


def test_grab_interrupts_generation_and_late_result_cannot_restore_old_location(pet_driver):
    c, service, worker, prep, now = pet_driver
    accepted = service.submit(
        "walking",
        expected_command_revision=service.get_world()["command_revision"],
        action={"kind": "move", "args": {"position": [0.5, 0]}},
    )
    assert accepted["status"] == "accepted"
    c.tick()
    assert c.active is not None and worker.pending is not None
    grab = intervene(c, service, "pointer-one", "grab_begin", target="avatar")
    assert service.get("walking")["status"] == "interrupted"
    assert c.active is None and c.trajectory is None
    intervene(c, service, "drop-one", "grab_end", grab_id=grab["grab_id"], position=[1, 0])
    dropped = copy.deepcopy(c.observation)
    worker.finish()
    c.tick()
    assert c.observation == dropped
    assert service.get_world()["avatar"]["position"] == [1, 0]
    assert c.job_id is None and c.future_segment is None


@pytest.mark.parametrize("buffered", [False, True])
def test_grab_invalidates_presence_preparation_and_future(pet_driver, buffered):
    c, service, worker, prep, now = pet_driver
    c.set_presence(True)
    c.tick()
    assert "speaks" not in worker.jobs[-1]["text"]
    worker.finish()
    c.tick()
    if buffered:
        prep.finish()
        c.tick()
        worker.finish()
        c.tick()
        prep.finish()
        c.tick()
        assert c._presence_future is not None
    grab = intervene(c, service, "grab", "grab_begin", target="avatar")
    frozen = copy.deepcopy(c.observation)
    if worker.pending:
        worker.finish()
    if prep.pending:
        prep.finish()
    now[0] += 0.5
    c.tick()
    assert c.observation == frozen
    assert c._presence_future is None and c._presence_segment is None
    intervene(c, service, "drop", "grab_end", grab_id=grab["grab_id"], position=[1, 0])
    c.tick()
    assert worker.jobs[-1]["start_pose"] == c.pose


def test_no_spectator_freezes_throw_and_resume_continues_from_checkpoint(pet_driver):
    c, service, worker, prep, now = pet_driver
    spawned = intervene(c, service, "ball", "spawn", model="ball", position=[2, 1, 0])
    intervene(c, service, "throw", "throw", object_id=spawned["object_id"], velocity=[1, 1, 0])
    now[0] += 0.1
    c.tick()
    c.set_viewing(False)
    frozen = copy.deepcopy(c.observation)
    for _ in range(5):
        now[0] += 0.2
        c.tick()
    assert c.observation == frozen
    assert service.get_world()["sandbox"]["suspended"]
    c.set_viewing(True)
    now[0] += 0.1
    c.tick()
    assert c.observation != frozen


def test_suspended_scene_refuses_body_actions(pet_driver):
    c, service, worker, prep, now = pet_driver
    c.set_viewing(False)
    outcome = service.submit(
        "no-hidden-walk",
        expected_command_revision=service.get_world()["command_revision"],
        action={"kind": "move", "args": {"position": [0.5, 0]}},
    )
    assert outcome["status"] == "rejected" and outcome["error"]["code"] == "sandbox_busy"
    c.tick()
    assert len(worker.jobs) == 1


def test_storage_failure_after_stopping_closes_the_driver_on_next_tick(pet_driver, monkeypatch):
    c, service, worker, prep, now = pet_driver

    def broken(value, observation, stop):
        stop()
        raise OSError("Synthetic storage failure")

    monkeypatch.setattr(c.pet, "apply", broken)
    with pytest.raises(OSError, match="storage"):
        intervene(c, service, "fault", "grab_begin", target="avatar")
    with pytest.raises(RuntimeError, match="could not be saved"):
        c.tick()


def test_pause_storage_rollback_after_stopping_closes_the_driver(pet_driver):
    c, service, worker, prep, now = pet_driver
    service.submit(
        "pause-fault-walk",
        expected_command_revision=service.get_world()["command_revision"],
        action={"kind": "move", "args": {"position": [0.5, 0]}},
    )
    c.tick()
    assert c.active is not None and worker.pending is not None
    before = service.runtime.snapshot()
    execution = service.get("pause-fault-walk")
    events = service.events()
    observation = copy.deepcopy(c.observation)
    with service.runtime.connection() as conn:
        conn.execute(
            "CREATE TRIGGER reject_pause BEFORE UPDATE ON world "
            "BEGIN SELECT RAISE(ABORT, 'pause storage failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="pause storage failure"):
        c.set_viewing(False)
    assert c.active is None and c.job_id is None
    assert c.viewing is True
    assert c.observation == observation
    assert service.runtime.snapshot() == before
    assert service.get("pause-fault-walk") == execution
    assert service.events() == events
    with service.runtime.connection() as conn:
        conn.execute("DROP TRIGGER reject_pause")
    # Even after storage recovers, the old dispatched action has no local driver.
    with pytest.raises(RuntimeError, match="Viewing change could not be saved"):
        c.tick()
    c.close()
    assert service.get("pause-fault-walk")["status"] == "interrupted"


def test_generic_presence_and_locomotion_do_not_move_a_held_object(pet_driver):
    c, service, worker, prep, now = pet_driver
    pose = c.observation["pose"]
    pose["positions"][10] = [0.5, 1, 0]
    appearance = c.observation["appearance"]
    appearance["core_pose_sha256"] = pose_digest(pose)
    appearance["aligned_hands"] = ["RightHand"]
    if appearance["version"] == 2:
        appearance["alignment_weights"] = {"RightHand": 1, "LeftHand": 0}
    c.observation["avatar"]["holding"] = "held"
    c.observation["objects"]["held"] = {
        "asset": "plush",
        "position": [0.7, 0],
        "spatial": {
            "position": [0.7, 1, 0],
            "rotation": IDENTITY,
            "attachment": {
                "joint": "RightHand",
                "position": [0.2, 0, 0],
                "rotation": IDENTITY,
            },
        },
    }
    c.handle.reconcile(c.observation, stopped=True)
    c.tick()
    assert len(worker.jobs) == 1 and c._presence_segment is None
    outcome = service.submit(
        "no-carry",
        expected_command_revision=service.get_world()["command_revision"],
        action={"kind": "move", "args": {"position": [0.5, 0]}},
    )
    assert outcome["status"] == "rejected" and "place" in outcome["error"]["message"]


@pytest.mark.parametrize("error", RETRYABLE_MOTION_ERRORS)
def test_idle_quality_retries_are_delayed_bounded_and_keep_the_observed_pose(pet_driver, error):
    c, service, worker, prep, now = pet_driver
    frozen = copy.deepcopy(c.observation)
    initial_jobs = len(worker.jobs)
    c.tick()
    first_seed = worker.jobs[-1]["seed"]
    for attempt in range(1, MAX_MOTION_ATTEMPTS + 1):
        assert len(worker.jobs) == initial_jobs + attempt
        assert worker.jobs[-1]["seed"] == first_seed + attempt - 1
        assert worker.jobs[-1]["start_pose"] == frozen["pose"]
        worker.finish(error=error)
        c.tick()
        assert c.presence_error and c.observation == frozen
        assert c._presence_quality_failures == attempt
        assert c._presence_segment is c._presence_future is None
        assert service.get_world()["pose"] == frozen["pose"]
        assert service.get_world()["appearance"] == frozen["appearance"]
        count = len(worker.jobs)
        now[0] += 0.99
        c.tick()
        assert len(worker.jobs) == count
        now[0] += 0.02
        c.tick()
    assert c.presence_status == "failed" and c.presence_error
    assert c._presence_retry_at is None
    for _ in range(5):
        now[0] += 1
        c.set_viewing(True)  # Repeated viewer notifications are not a new viewing.
        c.set_presence(True)
        c.tick()
    assert len(worker.jobs) == initial_jobs + MAX_MOTION_ATTEMPTS
    assert len(prep.jobs) == 1  # Only initialization; rejected poses never reach VRM preparation.


def test_only_accepted_playback_resets_consecutive_quality_failures(pet_driver):
    c, service, worker, prep, now = pet_driver
    c.tick()
    for _ in range(2):
        worker.finish(error=UNSUPPORTED_PHASE)
        c.tick()
        now[0] += 1
        c.tick()
    assert c._presence_quality_failures == 2
    worker.finish()
    c.tick()
    assert c._presence_quality_failures == 2
    prep.finish()
    c.tick()
    assert c.presence_status == "playing"
    assert c._presence_quality_failures == 2  # Origin frame is not a newly observed pose.
    now[0] += 0.05
    c.tick()
    assert c._presence_quality_failures == 0
    assert service.get_world()["pose"] == c.pose
    worker.finish(error=UNSUPPORTED_PHASE)  # Failure of the prepared-ahead continuation.
    c.tick()
    assert c._presence_quality_failures == 1 and c._presence_retry_at is not None
    frozen = copy.deepcopy(c.observation)
    now[0] += 1
    c.tick()
    assert worker.jobs[-1]["start_pose"] == frozen["pose"]


def test_pause_suppresses_retry_and_new_viewing_rearms_it(pet_driver):
    c, service, worker, prep, now = pet_driver
    c.tick()
    worker.finish(error=UNSUPPORTED_PHASE)
    c.tick()
    frozen = copy.deepcopy(c.observation)
    count = len(worker.jobs)
    c.set_viewing(False)
    c.set_presence(True)  # A speech notification cannot override the viewer/pause lease.
    for _ in range(3):
        now[0] += 1
        c.tick()
    assert len(worker.jobs) == count and c.observation == frozen
    assert c._presence_quality_failures == 1
    c.set_viewing(True)
    c.tick()
    assert c._presence_quality_failures == 0
    assert c.presence_error is None and len(worker.jobs) == count + 1
    assert worker.jobs[-1]["start_pose"] == frozen["pose"]


def test_new_intervention_rearms_idle_after_retry_budget_is_exhausted(pet_driver):
    c, service, worker, prep, now = pet_driver
    c.tick()
    for _ in range(MAX_MOTION_ATTEMPTS):
        worker.finish(error=UNSUPPORTED_PHASE)
        c.tick()
        now[0] += 1
        c.tick()
    assert c.presence_error and c._presence_retry_at is None
    count = len(worker.jobs)
    grab = intervene(c, service, "retry-grab", "grab_begin", target="avatar")
    assert c._presence_quality_failures == 0 and c.presence_error is None
    now[0] += 1
    c.tick()
    assert len(worker.jobs) == count  # A held avatar still suppresses idle.
    intervene(c, service, "retry-drop", "grab_end", grab_id=grab["grab_id"], position=[1, 0])
    frozen = copy.deepcopy(c.observation)
    c.tick()
    assert len(worker.jobs) == count + 1
    assert worker.jobs[-1]["start_pose"] == frozen["pose"]


@pytest.mark.parametrize(
    "error",
    [
        "ValueError: Unexpected trajectory filename.",
        "OSError: Synthetic storage failure",
        "TypeError: Synthetic programmer failure",
        "OSError: " + UNSUPPORTED_PHASE,
    ],
)
def test_non_quality_worker_failures_never_schedule_idle_retry(pet_driver, error):
    c, service, worker, prep, now = pet_driver
    c.tick()
    worker.finish(error=error)
    c.tick()
    assert c.presence_error and c._presence_retry_at is None
    count, frozen = len(worker.jobs), copy.deepcopy(c.observation)
    for _ in range(4):
        now[0] += 1
        c.tick()
    assert len(worker.jobs) == count and c.observation == frozen


def test_retry_does_not_bypass_visible_origin_validation(pet_driver):
    c, service, worker, prep, now = pet_driver
    c.tick()
    worker.finish(error=UNSUPPORTED_PHASE)
    c.tick()
    now[0] += 1
    c.tick()
    frozen = copy.deepcopy(c.observation)
    worker.finish()
    c.tick()
    prep.finish()
    prep.messages[-1]["appearance"]["frames"][0]["root_y_offset"] += 0.001
    c.tick()
    assert c.presence_error and c._presence_retry_at is None
    assert c._presence_segment is None and c.observation == frozen
