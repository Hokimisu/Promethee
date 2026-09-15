import copy

import pytest

from promethee.ardy_continuation import ActionTextEncoding, read_history
from promethee.motion_history import ExecutedHistory, write_history


def test_observed_history_is_bounded_and_drops_unobserved_time(articulated_pose):
    history = ExecutedHistory()
    for index in range(200):
        history.record(articulated_pose, index / 20)
    poses, committed = history.context()
    assert len(poses) == 160 and committed == 0
    poses[-1]["positions"][0][0] += 1
    assert history.samples[-1] == articulated_pose
    history.record(articulated_pose, 11)
    assert len(history.samples) == 1 and history.context() == ([], 0)
    history.record(articulated_pose, 11.01)
    assert len(history.samples) == 1


def test_committed_future_is_separate_and_immutable(articulated_pose):
    history = ExecutedHistory()
    for index in range(8):
        history.record(articulated_pose, index / 20)
    future = [copy.deepcopy(articulated_pose) for _ in range(40)]
    future[-1]["positions"][0][0] = 0.1
    poses, committed = history.context(future)
    assert len(poses) == 44 and committed == 40
    assert history.samples[-1] == articulated_pose
    assert poses[-1] == future[-1]
    poses[-1]["positions"][0][0] = 0.2
    assert future[-1]["positions"][0][0] == 0.1


def test_worker_history_is_bound_to_file_and_start_pose(tmp_path, articulated_pose):
    pytest.importorskip("numpy")
    job_id = "a" * 32
    poses = [copy.deepcopy(articulated_pose) for _ in range(8)]
    descriptor = write_history(tmp_path, job_id, poses, 4)
    job = {"job_id": job_id, "start_pose": articulated_pose, "history": descriptor}
    values = read_history(tmp_path, job)
    assert values["posed_joints"].shape == (8, 27, 3)
    assert descriptor["executed_frames"] == descriptor["committed_frames"] == 4
    altered = copy.deepcopy(job)
    altered["start_pose"]["positions"][0][0] += 0.01
    with pytest.raises(ValueError, match="starting pose"):
        read_history(tmp_path, altered)
    descriptor["executed_frames"] = 3
    with pytest.raises(ValueError, match="range"):
        read_history(tmp_path, job)
    descriptor["executed_frames"] = 4
    (tmp_path / descriptor["file"]).write_bytes(b"replaced")
    with pytest.raises(ValueError, match="differs"):
        read_history(tmp_path, job)


def test_text_encoding_is_reused_only_within_one_unchanged_action():
    class Encoder:
        def __init__(self):
            self.calls = []

        def _encode_text(self, texts):
            self.calls.append(texts)
            return object(), object()

    model = Encoder()
    cache = ActionTextEncoding(model)
    first, reused = cache.get("first", "walk")
    assert not reused
    assert cache.get("first", "walk") == (first, True)
    with pytest.raises(ValueError, match="new identity"):
        cache.get("first", "turn")
    second, reused = cache.get("second", "walk")
    assert not reused and second != first
    assert model.calls == [["walk"], ["walk"]]
