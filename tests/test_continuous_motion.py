"""Streaming orchestration with fake models; real motor qualification is separate."""

import copy

import pytest
from test_kinematic import driver as driver
from test_kinematic import submit
from test_prepared_kinematic import prepared_driver as prepared_driver

from promethee.ardy_continuation import read_history
from promethee.kinematic import read_trajectory


def path(poses, initial, start, end):
    poses[:] = [copy.deepcopy(initial) for _ in range(41)]
    for index in range(len(poses)):
        pose = copy.deepcopy(initial)
        for joint in pose["positions"]:
            joint[0] += start + (end - start) * index / (len(poses) - 1)
        poses[index] = pose


def test_generation_overlaps_playback_and_only_final_segment_completes(driver):
    pytest.importorskip("numpy")
    controller, service, worker, now, poses = driver
    controller.continuous_motion = True
    initial = copy.deepcopy(controller.pose)
    path(poses, initial, 0, 0.2)
    submit(service)
    controller.tick()
    assert worker.jobs[-1]["future_frames"] == 120
    worker.finish()
    controller.tick()
    assert controller.trajectory is not None and worker.pending is not None
    assert worker.jobs[-1]["future_frames"] == 80
    assert worker.jobs[-1]["stream_id"] == worker.jobs[-2]["stream_id"]
    assert worker.jobs[-1]["history"]["committed_frames"] == 40
    context = read_history(worker.output, worker.jobs[-1])
    assert context["posed_joints"][0, 0, 0] == pytest.approx(0.005)
    assert context["posed_joints"][-1, 0, 0] == pytest.approx(0.2)
    assert controller.pose["positions"][0][0] == 0
    path(poses, initial, 0.2, 0.4)
    worker.finish()
    controller.tick()
    assert controller.future_segment is not None
    assert service.get("move-one")["status"] == "running"
    now[0] += 2
    controller.tick()
    assert service.get("move-one")["status"] == "running"
    assert worker.jobs[-1]["future_frames"] == 40
    path(poses, initial, 0.4, 0.5)
    worker.finish()
    controller.tick()
    now[0] += 2
    controller.tick()
    assert service.get("move-one")["status"] == "running"
    now[0] += 2
    controller.tick()
    assert service.get("move-one")["status"] == "completed"
    assert service.get_world()["avatar"]["position"][0] == pytest.approx(0.5)
    assert len(worker.jobs) == 4  # Initial body plus three horizons.


def test_three_prepared_horizons_preserve_all_120_future_intervals(driver):
    pytest.importorskip("numpy")
    controller, service, worker, now, poses = driver
    controller.continuous_motion = True
    initial = copy.deepcopy(controller.pose)
    path(poses, initial, 0, 0.2)
    submit(service)
    controller.tick()
    worker.finish()
    controller.tick()
    first_start = controller.play_started
    endpoints = [(0, 0.2), (0.2, 0.4), (0.4, 0.5)]
    for segment, (start, end) in enumerate(endpoints):
        started = controller.play_started
        assert controller.frame == 0
        assert controller.pose["positions"][0][0] == pytest.approx(start)
        if segment < 2:
            path(poses, initial, *endpoints[segment + 1])
            worker.finish()
            controller.tick()
        for frame in (1, 38, 39):
            now[0] = started + frame / 20 + 1e-6
            controller.tick()
            assert controller.frame == frame
            assert controller.pose["positions"][0][0] == pytest.approx(
                start + (end - start) * frame / 40
            )
            assert service.get("move-one")["status"] == "running"
        now[0] = started + 2 + 1e-6
        controller.tick()
        assert controller.pose["positions"][0][0] == pytest.approx(end)
    assert service.get("move-one")["status"] == "completed"
    assert now[0] - first_start == pytest.approx(6, abs=1e-5)


def test_continuous_origin_cannot_replace_the_observed_core_pose(driver):
    controller, service, worker, _, poses = driver
    controller.continuous_motion = True
    path(poses, controller.pose, 0, 0.2)
    poses[0]["positions"][0][0] += 0.001
    before = copy.deepcopy(controller.observation)
    submit(service)
    controller.tick()
    worker.finish()
    controller.tick()
    assert service.get("move-one")["status"] == "failed"
    assert "observed Core pose" in service.get("move-one")["error"]["message"]
    assert controller.observation == before


def test_continuous_origin_cannot_recalculate_the_observed_appearance(prepared_driver):
    controller, service, worker, prep, _, poses = prepared_driver
    controller.continuous_motion = True
    path(poses, controller.pose, 0, 0.2)
    before = copy.deepcopy(controller.observation)
    submit(service)
    controller.tick()
    worker.finish()
    controller.tick()
    assert prep.jobs[-1]["observed_origin"] is True
    prep.finish()
    prep.messages[-1]["appearance"]["frames"][0]["root_y_offset"] += 0.001
    controller.tick()
    assert service.get("move-one")["status"] == "failed"
    assert "observed appearance" in service.get("move-one")["error"]["message"]
    assert controller.observation == before


def test_future_quality_retry_keeps_the_same_committed_context_while_body_moves(driver):
    np = pytest.importorskip("numpy")
    controller, service, worker, now, poses = driver
    controller.continuous_motion = True
    initial = copy.deepcopy(controller.pose)
    path(poses, initial, 0, 0.2)
    submit(service)
    controller.tick()
    worker.finish()
    controller.tick()
    first = worker.jobs[-1]
    context = read_history(worker.output, first)
    now[0] += 0.3
    controller.tick()
    current = copy.deepcopy(controller.pose)
    worker.messages.append(
        {
            "type": "error",
            "job_id": worker.pending,
            "error": "ValueError: Walking has a predicted phase without foot support.",
        }
    )
    controller.tick()
    retry = worker.jobs[-1]
    assert retry["job_id"] != first["job_id"]
    assert retry["start_pose"] == first["start_pose"] != current
    assert retry["seed"] == first["seed"] + 1
    assert retry["stream_id"] == first["stream_id"]
    retry_context = read_history(worker.output, retry)
    assert np.array_equal(context["posed_joints"], retry_context["posed_joints"])
    assert service.get("move-one")["status"] == "running"
    assert controller.pose == current


@pytest.mark.parametrize("stage", ["generation", "preparation", "buffered", "waiting"])
def test_cancel_discards_every_kind_of_future_without_replaying_it(prepared_driver, stage):
    pytest.importorskip("numpy")
    controller, service, worker, prep, now, poses = prepared_driver
    controller.continuous_motion = True
    initial = copy.deepcopy(controller.pose)
    path(poses, initial, 0, 0.2)
    submit(service)
    controller.tick()
    worker.finish()
    controller.tick()
    prep.finish()
    controller.tick()
    assert worker.pending is not None and controller.trajectory is not None
    now[0] += 0.4
    controller.tick()
    path(poses, initial, 0.2, 0.4)
    if stage in {"preparation", "buffered"}:
        worker.finish()
        controller.tick()
        assert prep.jobs[-1]["initial_pose"]["positions"][0][0] == pytest.approx(0.2)
        assert controller.pose["positions"][0][0] < 0.2
        if stage == "buffered":
            prep.finish()
            controller.tick()
            assert controller.future_segment is not None
    elif stage == "waiting":
        now[0] += 2
        controller.tick()
        assert controller.trajectory is None
        assert service.get("move-one")["status"] == "running"
    frozen = copy.deepcopy(controller.observation)
    service.cancel("move-one")
    controller.tick()
    if worker.pending is not None:
        worker.finish()
    if prep.pending is not None:
        prep.finish()
    controller.tick()
    assert controller.observation == frozen
    assert service.get("move-one")["observation"] == frozen
    assert service.get("move-one")["status"] == "cancelled"
    assert controller.future_segment is None and controller.trajectory is None
    submit(service, "new-intention", target=[-0.1, 0])
    controller.tick()
    assert worker.jobs[-1]["start_pose"] == frozen["pose"]
    assert worker.jobs[-1]["target"] == [-0.1, 0]
    assert worker.jobs[-1]["stream_id"] != worker.jobs[-2]["stream_id"]


def test_posture_final_target_stays_at_intention_even_when_intermediate_root_moves(
    driver, monkeypatch
):
    pytest.importorskip("numpy")
    controller, service, worker, now, poses = driver
    controller.continuous_motion = True
    initial = copy.deepcopy(controller.pose)
    targets = []

    def read(*args, **kwargs):
        targets.append(kwargs["target"])
        return copy.deepcopy(poses)

    monkeypatch.setattr("promethee.kinematic.read_trajectory", read)
    service.submit(
        "arms",
        service.get_world()["revision"],
        {"kind": "posture", "args": {"name": "arms_raised"}},
    )
    path(poses, initial, 0, 0.1)
    controller.tick()
    worker.finish()
    controller.tick()
    path(poses, initial, 0.1, 0.15)
    worker.finish()
    controller.tick()
    now[0] += 2
    controller.tick()
    assert controller.pose["positions"][0][0] == pytest.approx(0.1)
    path(poses, initial, 0.15, 0)
    worker.finish()
    controller.tick()
    assert targets == [None, None, [0.0, 0.0]]


def test_late_preparation_resumes_from_exact_observed_boundary(prepared_driver):
    pytest.importorskip("numpy")
    controller, service, worker, prep, now, poses = prepared_driver
    controller.continuous_motion = True
    initial = copy.deepcopy(controller.pose)
    path(poses, initial, 0, 0.2)
    submit(service)
    controller.tick()
    worker.finish()
    controller.tick()
    prep.finish()
    controller.tick()
    path(poses, initial, 0.2, 0.4)
    worker.finish()
    controller.tick()
    now[0] += 2
    controller.tick()
    stopped = copy.deepcopy(controller.observation)
    assert controller.trajectory is None
    now[0] += 0.5
    controller.tick()
    assert controller.observation == stopped
    prep.finish()
    controller.tick()
    assert controller.trajectory is not None
    assert controller.pose == stopped["pose"]
    assert service.get("move-one")["status"] == "running"


def test_rejected_future_stops_without_counting_the_destination_as_reached(driver):
    pytest.importorskip("numpy")
    controller, service, worker, now, poses = driver
    controller.continuous_motion = True
    initial = copy.deepcopy(controller.pose)
    path(poses, initial, 0, 0.2)
    submit(service)
    controller.tick()
    worker.finish()
    controller.tick()
    now[0] += 0.5
    controller.tick()
    stopped = copy.deepcopy(controller.observation)
    worker.messages.append({"type": "error", "job_id": worker.pending, "error": "bad contact"})
    controller.tick()
    assert service.get("move-one")["status"] == "failed"
    assert service.get("move-one")["observation"] == stopped
    assert controller.trajectory is None and controller.future_segment is None


def test_changed_committed_boundary_is_rejected_before_the_next_segment(driver):
    pytest.importorskip("numpy")
    controller, service, worker, now, poses = driver
    controller.continuous_motion = True
    initial = copy.deepcopy(controller.pose)
    path(poses, initial, 0, 0.2)
    submit(service)
    controller.tick()
    worker.finish()
    controller.tick()
    path(poses, initial, 0.2, 0.4)
    worker.finish()
    controller.tick()
    controller.future_segment["origin"]["avatar"]["position"][0] += 0.01
    now[0] += 2
    controller.tick()
    assert service.get("move-one")["status"] == "failed"
    assert controller.pose["positions"][0][0] == pytest.approx(0.2)
    assert len(worker.jobs) == 3  # No third generation from a mismatched boundary.


def test_wrong_horizon_cannot_shift_the_committed_timeline(driver):
    controller, service, worker, _, poses = driver
    controller.continuous_motion = True
    submit(service)
    controller.tick()
    worker.finish()
    controller.tick()
    assert service.get("move-one")["status"] == "failed"
    assert "40 future poses" in service.get("move-one")["error"]["message"]
    assert controller.trajectory is None and controller.future_segment is None


def test_intermediate_chunk_still_checks_geometry_but_not_final_destination(
    tmp_path, articulated_pose
):
    np = pytest.importorskip("numpy")
    positions = np.array([articulated_pose["positions"]] * 40)
    rotations = np.array([articulated_pose["rotations"]] * 40)
    archive = tmp_path / "chunk.npz"
    np.savez(
        archive,
        posed_joints=positions,
        global_rot_mats=rotations,
        foot_contacts=np.zeros((40, 4), dtype=bool),
        fps=20,
    )
    assert len(read_trajectory(archive, start_pose=articulated_pose, target=None)) == 40
    with pytest.raises(ValueError, match="misses the target"):
        read_trajectory(archive, start_pose=articulated_pose, target=[0.5, 0])
    positions[20, 0, 0] += 0.5
    np.savez(
        archive,
        posed_joints=positions,
        global_rot_mats=rotations,
        foot_contacts=np.zeros((40, 4), dtype=bool),
        fps=20,
    )
    with pytest.raises(ValueError, match="discontinuity"):
        read_trajectory(archive, start_pose=articulated_pose, target=None)


@pytest.mark.parametrize("shift,error", [(0.13, "discontinuity"), (0.02, "contact feet slide")])
def test_observed_origin_does_not_hide_first_future_interval_violations(
    tmp_path, articulated_pose, shift, error
):
    np = pytest.importorskip("numpy")
    positions = np.array([articulated_pose["positions"]] * 41)
    rotations = np.array([articulated_pose["rotations"]] * 41)
    positions[1:, :, 0] += shift
    archive = tmp_path / "anchored.npz"
    np.savez(
        archive,
        posed_joints=positions,
        global_rot_mats=rotations,
        foot_contacts=np.ones((41, 4), dtype=bool),
        fps=20,
    )
    with pytest.raises(ValueError, match=error):
        read_trajectory(archive, start_pose=articulated_pose, target=None)
