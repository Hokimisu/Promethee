"""Controller orchestration with fake generation/preparation, not motion qualification."""

import copy
from collections import deque

import pytest
from test_kinematic import Worker, submit

from promethee.avatar_reach import load_profile
from promethee.execution import ExecutionService
from promethee.kinematic import KinematicController
from promethee.prepared_avatar import EXTRA_BONES
from promethee.runtime import Runtime
from promethee.world import ActionError


class Preparation:
    def __init__(self):
        self.pending = None
        self.jobs = []
        self.messages = deque()
        self.cancellations = 0

    def submit(self, document, *, mode):
        assert self.pending is None
        self.jobs.append(copy.deepcopy(document))
        self.pending = str(len(self.jobs))
        return self.pending

    def finish(self, error=None):
        profile = load_profile()
        document = self.jobs[-1]
        artifact = {
            "version": 1,
            "avatar_sha256": profile["asset_sha256"],
            "scale": profile["scale"],
            "aligned_hands": [],
            "mode": "--settle",
            "frames": [
                {
                    "root_y_offset": -0.02,
                    "rotations": {
                        name: [0, 0, 0, 1] for name in set(profile["bones"]) | set(EXTRA_BONES)
                    },
                }
                for _ in document["frames"]
            ],
        }
        self.messages.append(
            {
                "type": "error" if error else "prepared",
                "job_id": self.pending,
                "appearance": artifact,
                "error": error,
            }
        )

    def poll(self):
        if self.messages:
            self.pending = None
            return self.messages.popleft()

    def cancel(self):
        if self.pending is not None:
            self.cancellations += 1

    def close(self):
        self.cancel()


@pytest.fixture
def prepared_driver(tmp_path, articulated_pose, monkeypatch):
    now = [1000.0]
    service = ExecutionService(
        Runtime(tmp_path / "world.sqlite3", data_origin="session"), clock=lambda: now[0]
    )
    worker, preparation = Worker(tmp_path), Preparation()
    poses = [copy.deepcopy(articulated_pose) for _ in range(40)]
    monkeypatch.setattr(
        "promethee.kinematic.read_trajectory", lambda *a, **kw: copy.deepcopy(poses)
    )
    monkeypatch.setattr(
        "promethee.kinematic.read_contact_flags", lambda *a: [[True] * 4 for _ in poses]
    )
    controller = KinematicController(
        service,
        worker,
        clock=lambda: now[0],
        appearance_preparation=preparation,
        object_interactions=True,
    )
    controller.tick()
    worker.finish()
    controller.tick()
    assert not controller.ready and service.get_world()["pose"] is None
    preparation.finish()
    controller.tick()
    assert controller.ready and service.get_world()["appearance"] is not None
    try:
        yield controller, service, worker, preparation, now, poses
    finally:
        controller.close()


def test_preparation_waits_and_late_cancelled_poses_are_never_played(prepared_driver):
    controller, service, worker, preparation, _, _ = prepared_driver
    before = copy.deepcopy(controller.observation)
    submit(service)
    controller.tick()
    worker.finish()
    controller.tick()
    assert controller.trajectory is None
    assert controller.observation == before
    assert preparation.jobs[-1]["initial_appearance"] == before["appearance"]
    service.cancel("move-one")
    controller.tick()
    assert preparation.cancellations == 1
    assert service.get("move-one")["status"] == "cancelled"
    preparation.finish()
    controller.tick()
    assert controller.observation == before and controller.trajectory is None


def test_prepared_playback_cancel_and_restore_keep_the_same_appearance(prepared_driver):
    controller, service, worker, preparation, now, poses = prepared_driver
    for index, pose in enumerate(poses):
        for point in pose["positions"]:
            point[0] = index / 78
    submit(service)
    controller.tick()
    worker.finish()
    controller.tick()
    preparation.finish()
    controller.tick()
    now[0] += 0.8
    controller.tick()
    last = copy.deepcopy(controller.observation)
    service.cancel("move-one")
    controller.tick()
    assert service.get("move-one")["observation"] == last
    controller.close()
    with pytest.raises(ActionError, match="prepared appearance mode"):
        KinematicController(service, Worker(worker.output))
    fresh = Preparation()
    restored = KinematicController(
        service, Worker(worker.output), clock=lambda: now[0], appearance_preparation=fresh
    )
    try:
        restored.tick()
        assert restored.ready and restored.observation == last
        assert fresh.jobs == []
        assert service.get("move-one")["status"] == "cancelled"
    finally:
        restored.close()


def test_preparation_failure_preserves_the_confirmed_visible_pose(prepared_driver):
    controller, service, worker, preparation, _, _ = prepared_driver
    before = copy.deepcopy(controller.observation)
    submit(service)
    controller.tick()
    worker.finish()
    controller.tick()
    preparation.finish(error="visible support refused")
    controller.tick()
    assert service.get("move-one")["status"] == "failed"
    assert controller.observation == before and controller.trajectory is None


def test_spawn_preserves_appearance_without_repreparing_the_body(prepared_driver):
    pytest.importorskip("numpy")
    controller, service, _, preparation, _, _ = prepared_driver
    appearance = copy.deepcopy(controller.observation["appearance"])
    service.submit(
        "spawn",
        service.get_world()["revision"],
        {"kind": "spawn", "args": {"object_id": "ball", "asset": "ball", "position": [1, 1, 1]}},
    )
    controller.tick()
    controller.tick()
    assert service.get("spawn")["status"] == "completed"
    assert controller.observation["appearance"] == appearance
    assert len(preparation.jobs) == 1
