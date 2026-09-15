"""Deterministic driver tests; synthetic poses are not motor qualification."""

import copy
from collections import deque

import pytest

from promethee.execution import ExecutionService
from promethee.kinematic import KinematicController
from promethee.runtime import Runtime


class Worker:
    def __init__(self, output):
        self.output = output
        self.pending = None
        self.messages = deque([{"type": "ready", "skeleton": {}}])
        self.jobs = []
        self.closed = False

    def poll(self):
        if not self.messages:
            return None
        item = self.messages.popleft()
        if item["type"] in {"generated", "error"}:
            self.pending = None
        return item

    def submit(self, job):
        assert self.pending is None
        self.pending = job["job_id"]
        self.jobs.append(copy.deepcopy(job))

    def finish(self):
        self.messages.append(
            {"type": "generated", "job_id": self.pending, "file": f"{self.pending}-processed.npz"}
        )

    def close(self):
        self.closed = True


@pytest.fixture
def driver(tmp_path, articulated_pose, monkeypatch):
    clock = [1000.0]
    service = ExecutionService(
        Runtime(tmp_path / "world.sqlite3", data_origin="session"), clock=lambda: clock[0]
    )
    worker = Worker(tmp_path)
    initial = copy.deepcopy(articulated_pose)
    poses = [copy.deepcopy(initial) for _ in range(40)]
    monkeypatch.setattr("promethee.kinematic.read_trajectory", lambda *a, **k: copy.deepcopy(poses))
    controller = KinematicController(service, worker, clock=lambda: clock[0])
    controller.tick()
    worker.finish()
    controller.tick()
    yield controller, service, worker, clock, poses
    controller.close()


def submit(service, rid="move-one", target=None):
    return service.submit(
        rid,
        service.get_world()["revision"],
        {"kind": "move", "args": {"position": target or [0.5, 0.0]}},
    )


def test_intention_does_not_teleport_and_playback_persists(driver):
    controller, service, worker, clock, poses = driver
    assert submit(service)["status"] == "accepted"
    controller.tick()
    assert service.get_world()["avatar"]["position"] == [0.0, 0.0]
    for i, pose in enumerate(poses):
        for joint in pose["positions"]:
            joint[0] = i / 78
    worker.finish()
    controller.tick()
    clock[0] += 1
    controller.tick()
    assert 0 < service.get_world()["avatar"]["position"][0] < 0.5
    clock[0] += 1
    controller.tick()
    assert service.get("move-one")["status"] == "completed"
    assert service.get_world()["pose"] == poses[-1]


def test_cancel_before_dispatch_never_generates(driver):
    controller, service, worker, _, _ = driver
    submit(service)
    service.cancel("move-one")
    controller.tick()
    assert len(worker.jobs) == 1  # Body initialization only.
    assert service.get("move-one")["status"] == "cancelled"


def test_cancel_during_generation_discards_late_result(driver):
    controller, service, worker, _, _ = driver
    submit(service)
    controller.tick()
    before = copy.deepcopy(controller.pose)
    service.cancel("move-one")
    controller.tick()
    assert service.get("move-one")["status"] == "cancelled"
    assert submit(service, "move-two")["status"] == "accepted"
    controller.tick()
    assert len(worker.jobs) == 2
    worker.finish()
    controller.tick()
    assert controller.pose == before
    assert len(worker.jobs) == 3
    assert service.get("move-two")["status"] == "running"


def test_cancel_during_playback_keeps_exact_last_pose(driver):
    controller, service, worker, clock, poses = driver
    submit(service)
    controller.tick()
    for i, pose in enumerate(poses):
        for joint in pose["positions"]:
            joint[0] = i / 78
    worker.finish()
    controller.tick()
    clock[0] += 0.8
    controller.tick()
    last = copy.deepcopy(controller.pose)
    service.cancel("move-one")
    controller.tick()
    clock[0] += 1
    controller.tick()
    assert controller.pose == last == service.get_world()["pose"]
    assert service.get("move-one")["status"] == "cancelled"


def test_crash_and_restart_interrupt_without_replay(driver):
    controller, service, worker, clock, _ = driver
    submit(service)
    controller.tick()
    worker.messages.append({"type": "crashed", "error": "worker exited"})
    with pytest.raises(RuntimeError, match="worker exited"):
        controller.tick()
    last = copy.deepcopy(controller.pose)
    controller.close()
    assert service.get("move-one")["status"] == "interrupted"
    replacement_worker = Worker(worker.output)
    replacement = KinematicController(service, replacement_worker, clock=lambda: clock[0])
    try:
        replacement.tick()
        assert replacement_worker.jobs == []
        assert service.get_world()["pose"] == last
        assert service.get_world()["body"]["status"] == "confirmed"
        assert service.get("move-one")["status"] == "interrupted"
    finally:
        replacement.close()


def test_failed_posture_is_not_reported_complete(driver):
    controller, service, worker, clock, _ = driver
    service.submit(
        "posture-one",
        service.get_world()["revision"],
        {"kind": "posture", "args": {"name": "arms_raised"}},
    )
    controller.tick()
    worker.finish()
    controller.tick()
    clock[0] += 2
    controller.tick()
    assert service.get("posture-one")["status"] == "failed"
    assert service.get_world()["body"]["status"] == "confirmed"


def test_unqualified_distance_does_not_generate(driver):
    controller, service, worker, _, _ = driver
    submit(service, target=[4.0, 0.0])
    controller.tick()
    assert len(worker.jobs) == 1
    assert service.get("move-one")["status"] == "failed"


def test_expired_lease_stops_before_playback(driver):
    controller, service, _, clock, _ = driver
    submit(service)
    controller.tick()
    before = copy.deepcopy(controller.pose)
    clock[0] += 6
    with pytest.raises(RuntimeError, match="lease lost"):
        controller.tick()
    assert controller.pose == before
    assert service.get("move-one")["status"] == "interrupted"
