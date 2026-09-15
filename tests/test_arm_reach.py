"""Analytic arm geometry fixtures, not anatomical or grasp qualification."""

import copy

import pytest

from promethee.arm_reach import ARMS, forward_positions, interpolate_rotation, reach_arm

np = pytest.importorskip("numpy")


def fixture():
    names = [
        "Hips",
        "Spine",
        "Spine1",
        "Spine2",
        "Spine3",
        "Neck",
        "Head",
        "RightShoulder",
        "RightArm",
        "RightForeArm",
        "RightHand",
        "RightHandEnd",
        "RightHandThumb1",
        "LeftShoulder",
        "LeftArm",
        "LeftForeArm",
        "LeftHand",
        "LeftHandEnd",
        "LeftHandThumb1",
        "RightUpLeg",
        "RightLeg",
        "RightFoot",
        "RightToeBase",
        "LeftUpLeg",
        "LeftLeg",
        "LeftFoot",
        "LeftToeBase",
    ]
    parents = [
        -1,
        0,
        1,
        2,
        3,
        4,
        5,
        4,
        7,
        8,
        9,
        10,
        10,
        4,
        13,
        14,
        15,
        16,
        16,
        0,
        19,
        20,
        21,
        0,
        23,
        24,
        25,
    ]
    neutral = np.zeros((27, 3))
    neutral[1:7, 1] = np.arange(1, 7) * 0.1
    for side, sign in (("right", -1), ("left", 1)):
        a, b, c, d = [names.index(name) for name in ARMS[side]]
        neutral[[a, b, c, d]] = [
            [sign * 0.2, 0.5, 0],
            [sign * 0.35, 0.3, 0],
            [sign * 0.45, 0.1, 0.1],
            [sign * 0.5, 0.1, 0.1],
        ]
        neutral[a - 1] = [sign * 0.05, 0.5, 0]
        neutral[d + 1] = [sign * 0.47, 0.1, 0.13]
    skeleton = {"joint_names": names, "parents": parents, "neutral_joints": neutral.tolist()}
    matrices = np.repeat(np.eye(3)[None], 27, axis=0)
    points = forward_positions(matrices, np.array([0, 1, 0]), skeleton)
    pose = {"skeleton": "cskel27", "positions": points.tolist(), "rotations": matrices.tolist()}
    return skeleton, pose


@pytest.mark.parametrize("side", ["right", "left"])
def test_reach_preserves_bones_other_arm_and_local_hand_orientation(side):
    skeleton, pose = fixture()
    original = copy.deepcopy(pose)
    a, b, c, d = [skeleton["joint_names"].index(name) for name in ARMS[side]]
    target = (np.array(pose["positions"][a]) + [0, -0.2, 0.25]).tolist()
    result = reach_arm(pose, skeleton, target, side=side)
    points, rotations = result["posed_joints"], result["global_rot_mats"]
    assert pose == original
    np.testing.assert_allclose(points[-1, c], target, atol=1e-10)
    np.testing.assert_allclose(points[0], pose["positions"], atol=0)
    for joint, parent in enumerate(skeleton["parents"]):
        if parent >= 0:
            expected = np.linalg.norm(
                np.array(pose["positions"][joint]) - pose["positions"][parent]
            )
            np.testing.assert_allclose(
                np.linalg.norm(points[:, joint] - points[:, parent], axis=-1), expected, atol=1e-10
            )
    static = [i for i in range(27) if i not in {b, c, d, d + 1}]
    np.testing.assert_allclose(
        points[:, static],
        np.repeat(np.array(pose["positions"])[None, static], 61, axis=0),
        atol=1e-10,
    )
    local_hand = np.swapaxes(rotations[:, b], -1, -2) @ rotations[:, c]
    np.testing.assert_allclose(local_hand, np.repeat(np.eye(3)[None], 61, axis=0), atol=1e-10)
    np.testing.assert_allclose(np.linalg.det(rotations), 1, atol=1e-10)


def test_reach_is_equivariant_under_world_rotation_and_translation():
    skeleton, pose = fixture()
    target = [-0.2, 1.3, 0.3]
    expected = reach_arm(pose, skeleton, target)
    rotation = np.array([[0.0, 0, 1], [0, 1, 0], [-1, 0, 0]])
    translation = np.array([1.0, 0, -1])
    transformed = {
        "skeleton": "cskel27",
        "positions": (np.array(pose["positions"]) @ rotation.T + translation).tolist(),
        "rotations": (rotation @ np.array(pose["rotations"])).tolist(),
    }
    actual = reach_arm(transformed, skeleton, (rotation @ target + translation).tolist())
    np.testing.assert_allclose(
        actual["posed_joints"], expected["posed_joints"] @ rotation.T + translation, atol=1e-10
    )


@pytest.mark.parametrize("target", [[-0.2, 1.5, 0], [-2, 1, 0], [True, 1, 0], [0, float("nan"), 0]])
def test_unreachable_and_invalid_targets_are_refused(target):
    skeleton, pose = fixture()
    with pytest.raises(ValueError):
        reach_arm(pose, skeleton, target)


def test_skeleton_mismatch_and_nonfinite_rest_geometry_are_refused():
    skeleton, pose = fixture()
    pose["positions"][9][0] += 0.02
    with pytest.raises(ValueError, match="do not agree"):
        reach_arm(pose, skeleton, [-0.2, 1.3, 0.3])
    skeleton, pose = fixture()
    skeleton["neutral_joints"][26][0] = float("nan")
    with pytest.raises(ValueError, match="hierarchy"):
        reach_arm(pose, skeleton, [-0.2, 1.3, 0.3])


@pytest.mark.parametrize("pose", [None, {}, {"positions": []}])
def test_malformed_pose_is_refused(pose):
    skeleton, _ = fixture()
    with pytest.raises(ValueError):
        reach_arm(pose, skeleton, [-0.2, 1.3, 0.3])


@pytest.mark.parametrize("angle", [0, 0.4, np.pi - 1e-7, np.pi])
def test_rotation_interpolation_handles_half_turn_and_preserves_handedness(angle):
    c, s = np.cos(angle), np.sin(angle)
    end = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    values = np.array([interpolate_rotation(np.eye(3), end, p) for p in np.linspace(0, 1, 61)])
    np.testing.assert_allclose(values[0], np.eye(3), atol=1e-10)
    np.testing.assert_allclose(values[-1], end, atol=1e-8)
    np.testing.assert_allclose(
        values @ np.swapaxes(values, -1, -2), np.repeat(np.eye(3)[None], 61, axis=0), atol=1e-10
    )
    np.testing.assert_allclose(np.linalg.det(values), 1, atol=1e-10)


def test_requested_hand_orientation_and_descendants_reach_together():
    skeleton, pose = fixture()
    end = np.array([[0, -1.0, 0], [1.0, 0, 0], [0, 0, 1.0]])
    result = reach_arm(pose, skeleton, [-0.2, 1.3, 0.3], hand_rotation=end.tolist())
    matrices = result["global_rot_mats"]
    np.testing.assert_allclose(matrices[-1, 10], end, atol=1e-10)
    for joint in (11, 12):
        np.testing.assert_allclose(
            np.swapaxes(matrices[:, 10], -1, -2) @ matrices[:, joint],
            np.repeat(np.eye(3)[None], 61, axis=0),
            atol=1e-10,
        )
    np.testing.assert_allclose(result["posed_joints"][-1, 10], [-0.2, 1.3, 0.3], atol=1e-10)
    # Hand orientation is a world-space target, so rotate it with the world.
    turn = np.array([[0.0, 0, 1], [0, 1, 0], [-1, 0, 0]])
    moved = {
        **pose,
        "positions": (np.array(pose["positions"]) @ turn.T).tolist(),
        "rotations": (turn @ np.array(pose["rotations"])).tolist(),
    }
    actual = reach_arm(
        moved, skeleton, (turn @ [-0.2, 1.3, 0.3]).tolist(), hand_rotation=turn @ end
    )
    np.testing.assert_allclose(actual["posed_joints"], result["posed_joints"] @ turn.T, atol=1e-10)


@pytest.mark.parametrize(
    "matrix", [np.diag([-1.0, 1, 1]), np.zeros((3, 3)), [[float("nan")] * 3] * 3, [1, 2, 3]]
)
def test_invalid_contact_orientation_is_refused(matrix):
    skeleton, pose = fixture()
    with pytest.raises(ValueError, match="proper global rotation"):
        reach_arm(pose, skeleton, [-0.2, 1.3, 0.3], hand_rotation=matrix)


def test_half_turn_interpolation_tolerates_float32_pose_roundoff():
    end = np.diag([-1.0, -1.0, 1.0])
    start = np.eye(3) * (1 + 1e-7)
    actual = interpolate_rotation(start, end, 1.0)
    np.testing.assert_allclose(actual, end, atol=1e-10)


def test_repeated_reaching_does_not_accumulate_rotation_roundoff():
    skeleton, pose = fixture()
    pose["rotations"] = (np.array(pose["rotations"]) * (1 + 1e-7)).tolist()
    original = copy.deepcopy(pose)
    for i in range(6):
        result = reach_arm(pose, skeleton, [-0.2, 1.3, 0.25] if i % 2 else [-0.25, 1.25, 0.2])
        if i == 0:
            np.testing.assert_allclose(result["global_rot_mats"][0], original["rotations"], atol=0)
        matrices = result["global_rot_mats"][-1]
        np.testing.assert_allclose(
            matrices @ np.swapaxes(matrices, -1, -2),
            np.repeat(np.eye(3)[None], 27, axis=0),
            atol=1e-12,
        )
        pose = {
            "skeleton": "cskel27",
            "positions": result["posed_joints"][-1].tolist(),
            "rotations": matrices.tolist(),
        }
