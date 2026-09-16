"""CPU orchestration tests; the synthetic poses are not ARDY quality evidence."""

import copy
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from presence import PRESENCE_TEXT, PresenceController

from promethee.execution import ExecutionService
from promethee.runtime import Runtime
from promethee.world import ActionError

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests"))
# Reuse the explicit synthetic controller fixtures, without copying their logic.
from test_kinematic import Worker, submit  # noqa: E402
from test_prepared_kinematic import Preparation  # noqa: E402


class MotionWorker(Worker):
    def finish(self, *, root_shift=0, bad_origin=False, error=None):
        job = self.jobs[-1]
        if error:
            self.messages.append({"type": "error", "job_id": self.pending, "error": error})
            return
        initial = job["start_pose"] or {
            "skeleton": "cskel27",
            "positions": [[0.0, 1.0, 0.0] for _ in range(27)],
            "rotations": [[[1, 0, 0], [0, 1, 0], [0, 0, 1]] for _ in range(27)],
        }
        count = 41 if "stream_id" in job else job["frames"]
        positions = np.asarray([initial["positions"] for _ in range(count)], dtype=float)
        rotations = np.asarray([initial["rotations"] for _ in range(count)], dtype=float)
        # Some visible motion, but planted feet and an exact observed origin.
        positions[:, 10, 0] += np.linspace(0, 0.03, count)
        positions[:, :, 0] += np.linspace(0, root_shift, count)[:, None]
        if bad_origin:
            positions[0, 10, 0] += 0.001
        np.savez(
            self.output / f"{self.pending}-processed.npz",
            posed_joints=positions,
            global_rot_mats=rotations,
            foot_contacts=np.ones((count, 4), dtype=bool),
            fps=20,
        )
        super().finish()


@pytest.fixture
def driver(tmp_path):
    now = [1000.0]
    service = ExecutionService(
        Runtime(tmp_path / "world.sqlite3", data_origin="session"), clock=lambda: now[0]
    )
    worker, prep = MotionWorker(tmp_path), Preparation()
    controller = PresenceController(
        service, worker, clock=lambda: now[0], continuous_motion=True, appearance_preparation=prep
    )
    controller.tick()
    worker.finish()
    controller.tick()
    prep.finish()
    controller.tick()
    assert controller.ready
    yield controller, service, worker, prep, now
    controller.close()


def ready_presence(driver):
    controller, service, worker, prep, now = driver
    controller.set_presence(True)
    controller.tick()
    worker.finish()
    controller.tick()
    prep.finish()
    controller.tick()
    assert controller.presence_status == "playing"
    return controller, service, worker, prep, now


def test_explicit_only_real_stream_contract_and_no_fake_execution(driver):
    c, service, worker, prep, now = driver
    for _ in range(4):
        now[0] += 0.05
        c.tick()
    assert len(worker.jobs) == 1
    initial = copy.deepcopy(c.observation)
    c.set_presence(True)
    c.tick()
    job = worker.jobs[-1]
    assert job["text"] == PRESENCE_TEXT and job["posture"] is None
    assert job["frames"] == job["future_frames"] == 40
    assert job["start_pose"] == initial["pose"] and job["history"]["frames"] >= 4
    assert c.active is None and c.observation == initial
    record = json.loads((worker.output / f"{job['job_id']}-request.json").read_text())
    assert record["purpose"] == "body-presence" and record["request_id"] is None
    worker.finish()
    c.tick()
    assert prep.jobs[-1]["observed_origin"] is True
    assert prep.jobs[-1]["initial_appearance"] == initial["appearance"]
    prep.finish()
    c.tick()
    assert c.observation == initial
    assert worker.jobs[-1]["stream_id"] == job["stream_id"]
    assert worker.jobs[-1]["history"]["committed_frames"] == 40
    now[0] += 0.2
    c.tick()
    assert c.pose != initial["pose"]
    assert service.get_world()["pose"] == c.pose
    with service.runtime.connection() as conn:
        assert conn.execute("SELECT count(*) FROM executions").fetchone()[0] == 0


def test_two_horizons_join_at_the_observed_origin_without_replay(driver):
    c, service, worker, prep, now = ready_presence(driver)
    first = c._presence_segment
    worker.finish()
    c.tick()
    prep.finish()
    c.tick()
    assert c._presence_future is not None
    assert c._presence_future["origin"]["pose"] == first["poses"][-1]
    now[0] += 2
    c.tick()
    assert c.pose == first["poses"][-1]
    assert c._presence_frame == 0
    now[0] += 0.05
    c.tick()
    assert c.pose != first["poses"][-1]


@pytest.mark.parametrize("stage", ["generation", "preparation", "playing", "buffered"])
def test_stop_invalidates_every_late_horizon(driver, stage):
    c, service, worker, prep, now = driver
    c.set_presence(True)
    c.tick()
    if stage != "generation":
        worker.finish()
        c.tick()
    if stage in {"playing", "buffered"}:
        prep.finish()
        c.tick()
        now[0] += 0.3
        c.tick()
    if stage == "buffered":
        worker.finish()
        c.tick()
        prep.finish()
        c.tick()
    frozen = copy.deepcopy(c.observation)
    c.set_presence(False)
    if worker.pending is not None:
        worker.finish()
    if prep.pending is not None:
        prep.finish()
    now[0] += 0.5
    c.tick()
    assert c.observation == frozen and service.get_world()["pose"] == frozen["pose"]
    assert c._presence_segment is c._presence_future is None
    assert c.presence_status == "disabled"


def test_accepted_action_preempts_presence_and_late_result(driver):
    c, service, worker, prep, now = ready_presence(driver)
    now[0] += 0.3
    c.tick()
    frozen = copy.deepcopy(c.observation)
    submit(service)
    now[0] += 0.1
    c.tick()
    assert c.observation == frozen and c._presence_segment is None
    worker.finish()
    c.tick()
    assert c.active["request_id"] == "move-one"
    assert worker.jobs[-1]["text"] == "A person walks to the target and stops."
    assert worker.jobs[-1]["start_pose"] == frozen["pose"]
    assert c.presence_status == "preempted"


def test_acceptance_race_rolls_back_pose_and_appearance_before_publish(driver, monkeypatch):
    c, service, worker, prep, now = ready_presence(driver)
    frozen = copy.deepcopy(c.observation)
    observe = c.handle.observe_idle

    def race(observation):
        submit(service)
        return observe(observation)

    monkeypatch.setattr(c.handle, "observe_idle", race)
    now[0] += 0.1
    c.tick()
    assert c.observation == frozen
    assert service.get_world()["pose"] == frozen["pose"]
    assert service.get_world()["appearance"] == frozen["appearance"]
    assert c._presence_segment is None
    assert service.get("move-one")["status"] == "accepted"


@pytest.mark.parametrize("failure", ["core", "appearance", "quality"])
def test_failure_is_latched_without_killing_ready_body(driver, failure):
    c, service, worker, prep, now = driver
    frozen = copy.deepcopy(c.observation)
    c.set_presence(True)
    c.tick()
    worker.finish(
        bad_origin=failure == "core", error="bad support" if failure == "quality" else None
    )
    c.tick()
    if failure == "appearance":
        prep.finish()
        prep.messages[-1]["appearance"]["frames"][0]["root_y_offset"] += 0.001
        c.tick()
    count = len(worker.jobs)
    for _ in range(5):
        now[0] += 0.1
        c.tick()
    assert c.ready and c.observation == frozen and c.presence_error
    assert c.presence_status == "failed" and len(worker.jobs) == count
    c.set_presence(True)
    c.tick()
    assert len(worker.jobs) == count
    c.set_presence(False)
    c.set_presence(True)
    c.tick()
    assert len(worker.jobs) == count + 1


def test_lease_loss_never_publishes_the_candidate(driver, monkeypatch):
    c, service, worker, prep, now = ready_presence(driver)
    frozen = copy.deepcopy(c.observation)
    monkeypatch.setattr(c.handle, "observe_idle", lambda observation: False)
    now[0] += 0.1
    with pytest.raises(RuntimeError, match="ownership"):
        c.tick()
    assert c.observation == frozen


def test_presence_accepts_six_centimetres_with_the_authorized_one_metre_anchor(driver):
    c, service, worker, prep, now = driver
    initial = copy.deepcopy(c.observation)
    c.set_presence(True)
    c.tick()
    worker.finish(root_shift=0.06)
    c.tick()
    assert c.presence_status == "preparing" and c.presence_error is None
    prep.finish()
    c.tick()
    now[0] += 2
    c.tick()
    assert c.observation["avatar"]["position"][0] == pytest.approx(0.06)
    assert c._presence_anchor == initial["avatar"]["position"]


def test_presence_rejects_more_than_one_metre_from_its_original_anchor(driver):
    c, service, worker, prep, now = driver
    initial = copy.deepcopy(c.observation)
    c.set_presence(True)
    c.tick()
    worker.finish(root_shift=1.01)
    c.tick()
    assert c.presence_status == "failed"
    assert "misses the target by more than 1 m" in c.presence_error
    assert c.observation == initial


def test_generation_timeout_is_latched_and_late_result_is_never_played(driver):
    c, service, worker, prep, now = driver
    initial = copy.deepcopy(c.observation)
    c.set_presence(True)
    c.tick()
    count = len(worker.jobs)
    for _ in range(122):
        now[0] += 0.5
        c.tick()
    assert c.ready and c.presence_status == "failed"
    assert "60 seconds" in c.presence_error
    worker.finish()
    c.tick()
    assert c.observation == initial and len(worker.jobs) == count


def test_observation_validation_failure_is_not_disguised_as_preemption(driver, monkeypatch):
    c, service, worker, prep, now = ready_presence(driver)
    frozen = copy.deepcopy(c.observation)

    def invalid(observation):
        raise ActionError("invalid observed appearance")

    monkeypatch.setattr(c.handle, "observe_idle", invalid)
    now[0] += 0.1
    c.tick()
    assert c.observation == frozen
    assert c.presence_status == "failed"
    assert c.presence_error == "invalid observed appearance"
