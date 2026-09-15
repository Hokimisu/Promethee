"""CPU contract for the stream boundary; no model inference or quality claim."""

from types import SimpleNamespace

import pytest

from promethee.ardy_worker import prepend_observed_origin


def test_origin_is_separate_from_all_40_future_samples(articulated_pose):
    np = pytest.importorskip("numpy")
    articulated_pose["positions"][0][0] = 0.12345678912345
    angle = 0.12345678912345
    articulated_pose["rotations"][0] = [
        [float(np.cos(angle)), 0, float(np.sin(angle))],
        [0, 1, 0],
        [-float(np.sin(angle)), 0, float(np.cos(angle))],
    ]
    skeleton = SimpleNamespace(joint_parents=[-1] + [0] * 26, hip_joint_idx=[19, 23])
    points = np.asarray(articulated_pose["positions"], dtype=np.float32)
    matrices = np.asarray(articulated_pose["rotations"], dtype=np.float32)
    future = {
        "posed_joints": np.stack([points + [i / 1000, 0, 0] for i in range(1, 41)]),
        "global_rot_mats": np.repeat(matrices[None], 40, axis=0),
        "local_rot_mats": np.repeat(matrices[None], 40, axis=0),
        "root_positions": np.repeat(points[0][None], 40, axis=0),
        "smooth_root_pos": np.repeat(points[0][None], 40, axis=0),
        "global_root_heading": np.tile([1.0, 0.0], (40, 1)),
        "foot_contacts": np.ones((40, 4), dtype=bool),
    }
    original = {key: value.copy() for key, value in future.items()}
    joined = prepend_observed_origin(future, articulated_pose, skeleton, [True, False] * 2)
    for key, value in original.items():
        assert len(joined[key]) == 41
        assert np.array_equal(joined[key][1:], value)
        assert np.array_equal(future[key], value)
    assert joined["posed_joints"][0].tolist() == articulated_pose["positions"]
    assert joined["global_rot_mats"][0].tolist() == articulated_pose["rotations"]
    assert joined["foot_contacts"][0].tolist() == [True, False] * 2
    assert np.max(np.abs(joined["posed_joints"][1] - points)) > 0
    with pytest.raises(ValueError, match="40 decoded"):
        prepend_observed_origin(joined, articulated_pose, skeleton, [True] * 4)
