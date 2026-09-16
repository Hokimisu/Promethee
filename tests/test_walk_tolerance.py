"""Arrival policy tests with numeric CPU trajectories, not motor qualification."""

import copy
import json
from pathlib import Path

import pytest
from test_kinematic import driver as driver
from test_kinematic import submit

from promethee.kinematic import (
    DEFAULT_TARGET_TOLERANCE_M,
    FREE_WALK_TARGET_TOLERANCE_M,
    read_trajectory,
)

np = pytest.importorskip("numpy")


def archive(path, start, destination_x, count=40):
    positions = np.repeat(np.asarray(start["positions"])[None], count, axis=0)
    positions[:, :, 0] += np.linspace(0, destination_x - positions[0, 0, 0], count)[:, None]
    np.savez(
        path,
        posed_joints=positions,
        global_rot_mats=np.repeat(np.asarray(start["rotations"])[None], count, axis=0),
        foot_contacts=np.zeros((count, 4), dtype=bool),
        fps=20,
    )
    return positions


@pytest.mark.parametrize("continuous", [False, True])
def test_free_walk_accepts_six_cm_error_and_persists_actual_position(
    driver, monkeypatch, continuous
):
    controller, service, worker, now, _ = driver
    controller.continuous_motion = continuous
    calls = []

    def checked_read(*args, **kwargs):
        calls.append(kwargs)
        return read_trajectory(*args, **kwargs)

    monkeypatch.setattr("promethee.kinematic.read_trajectory", checked_read)
    submit(service, target=[0.5, 0])
    controller.tick()
    actual_x = 0.5 - 0.06059
    for end in [0.15, 0.3, actual_x] if continuous else [actual_x]:
        job = worker.jobs[-1]
        archive(
            worker.output / f"{job['job_id']}-processed.npz",
            job["start_pose"],
            end,
            count=41 if continuous else 40,
        )
        worker.finish()
        controller.tick()
        now[0] += 2.000001
        controller.tick()
    assert service.get("move-one")["status"] == "completed"
    world = service.get_world()
    assert world["avatar"]["position"] == pytest.approx([actual_x, 0])
    assert world["pose"]["positions"][0][0] == pytest.approx(actual_x)
    assert service.get("move-one")["observation"]["avatar"]["position"] == pytest.approx(
        [actual_x, 0]
    )
    assert world["avatar"]["position"] != [0.5, 0]
    assert all(call["target_tolerance_m"] == 1.0 for call in calls)
    assert calls[-1]["target"] == [0.5, 0]


@pytest.mark.parametrize("kind,error_m", [("move", 1.00001), ("posture", 0.06059)])
def test_arrival_rejection_preserves_the_observation(driver, monkeypatch, kind, error_m):
    controller, service, worker, _, _ = driver
    monkeypatch.setattr("promethee.kinematic.read_trajectory", read_trajectory)
    before = copy.deepcopy(controller.observation)
    if kind == "move":
        submit(service, target=[0.5, 0])
        target_x = 0.5
        request_id = "move-one"
    else:
        request_id = "posture-one"
        service.submit(
            request_id,
            service.get_world()["revision"],
            {"kind": "posture", "args": {"name": "arms_raised"}},
        )
        target_x = 0
    controller.tick()
    job = worker.jobs[-1]
    archive(worker.output / f"{job['job_id']}-processed.npz", job["start_pose"], target_x + error_m)
    worker.finish()
    controller.tick()
    assert service.get(request_id)["status"] == "failed"
    assert "misses the target" in service.get(request_id)["error"]["message"]
    assert controller.observation == before
    assert controller.trajectory is None


def test_free_walk_one_metre_boundary_does_not_disable_stability(tmp_path, articulated_pose):
    path = tmp_path / "motion.npz"
    positions = archive(path, articulated_pose, 0.5)
    assert (
        len(
            read_trajectory(
                path, start_pose=articulated_pose, target=[-0.5, 0], target_tolerance_m=1.0
            )
        )
        == 40
    )
    with pytest.raises(ValueError, match="misses the target"):
        read_trajectory(
            path, start_pose=articulated_pose, target=[-0.50001, 0], target_tolerance_m=1.0
        )
    with pytest.raises(ValueError, match="misses the target"):
        read_trajectory(path, start_pose=articulated_pose, target=[0.5 + 0.06059, 0])
    positions[20, 0, 0] += 0.2
    with np.load(path) as saved:
        content = {key: saved[key].copy() for key in saved.files}
    np.savez(path, **(content | {"posed_joints": positions}))
    with pytest.raises(ValueError, match="discontinuity"):
        read_trajectory(path, start_pose=articulated_pose, target=[0.5, 0], target_tolerance_m=1.0)


def test_runtime_criteria_distinguish_arrival_policy_from_stability():
    criteria = json.loads(
        (
            Path(__file__).resolve().parents[1] / "experiments/motion/runtime-criteria.json"
        ).read_text()
    )
    assert criteria["version"] == 5
    assert criteria["target_error_max_m"] == DEFAULT_TARGET_TOLERANCE_M == 0.05
    assert criteria["free_walk_target_error_max_m"] == FREE_WALK_TARGET_TOLERANCE_M == 1.0
    assert criteria["floor_lift_max_m"] == 0.05
    assert criteria["root_frame_step_max_m"] == 0.12
    assert criteria["geometric_sole_speed_max_m_s"] == 0.2
    assert criteria["walking_surface_contact_frame_fraction_min"] == 1.0
