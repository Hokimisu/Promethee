"""Analytic reach tests; the real VRM comparison is a separate qualification."""

import copy

import pytest
from test_arm_reach import fixture

from promethee.avatar_reach import PixivArmReach

np = pytest.importorskip("numpy")


def example():
    skeleton, pose = fixture()
    reach = PixivArmReach()
    # The analytic fixture supplies names and a valid pose. Only rest height is
    # used to verify the appearance scale; this does not turn it into Core data.
    skeleton["neutral_joints"] = [[0, 0, 0] for _ in range(27)]
    skeleton["neutral_joints"][21][1] = -reach.profile["core_hip_height"]
    bones = reach.profile["bones"]
    shoulder = (
        np.asarray(pose["positions"][0])
        + (np.asarray(bones["rightUpperArm"]["rest_position"]) - bones["hips"]["rest_position"])
        * reach.profile["scale"]
    )
    pose["rotations"] = np.repeat(np.eye(3)[None], 27, axis=0).tolist()
    pose["positions"][10] = (shoulder + [0, -0.2, 0.1]).tolist()
    return reach, skeleton, pose, shoulder


def test_reach_is_invariant_under_world_rotation_and_translation():
    reach, skeleton, pose, _ = example()
    before = copy.deepcopy(pose)
    measured = reach.check(pose, skeleton, "RightHand")
    assert pose == before
    rotation = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]])
    pose["positions"] = (np.asarray(pose["positions"]) @ rotation.T + [1, 0, -1]).tolist()
    pose["rotations"] = (rotation @ np.asarray(pose["rotations"])).tolist()
    assert reach.check(pose, skeleton, "RightHand") == pytest.approx(measured)


@pytest.mark.parametrize("distance", [0.0, 0.46, 1.0])
def test_reach_rejects_inner_and_outer_unreachable_wrist(distance):
    reach, skeleton, pose, shoulder = example()
    pose["positions"][10] = (shoulder + [0, 0, distance]).tolist()
    with pytest.raises(ValueError, match="pixiv avatar arm reach"):
        reach.check(pose, skeleton, "RightHand")


def test_changed_rest_height_cannot_reuse_the_appearance_scale():
    reach, skeleton, pose, _ = example()
    skeleton["neutral_joints"][21][1] -= 0.01
    with pytest.raises(ValueError, match="rest height"):
        reach.check(pose, skeleton, "RightHand")


def test_root_lowering_changes_reach_without_moving_the_observed_hand():
    reach, skeleton, pose, shoulder = example()
    pose["positions"][10] = (shoulder + [0, 0.45, 0]).tolist()
    before = copy.deepcopy(pose)
    assert reach.check(pose, skeleton, "RightHand")["distance_m"] == pytest.approx(0.45)
    with pytest.raises(ValueError, match="pixiv avatar arm reach"):
        reach.check(pose, skeleton, "RightHand", root_y_offset=-0.02)
    assert reach.check(pose, skeleton, "RightHand", root_y_offset=0.02)[
        "distance_m"
    ] == pytest.approx(0.43)
    assert pose == before


def test_root_offset_preserves_the_inner_reach_limit():
    reach, skeleton, pose, shoulder = example()
    pose["positions"][10] = (shoulder + [0, 0.02, 0]).tolist()
    reach.check(pose, skeleton, "RightHand")
    with pytest.raises(ValueError, match="pixiv avatar arm reach"):
        reach.check(pose, skeleton, "RightHand", root_y_offset=0.02)


@pytest.mark.parametrize(
    "offset", [True, "0.01", None, float("nan"), float("inf"), -0.0501, 0.0501]
)
def test_invalid_root_offset_cannot_bypass_reach_checks(offset):
    reach, skeleton, pose, _ = example()
    with pytest.raises(ValueError, match="height offset"):
        reach.check(pose, skeleton, "RightHand", root_y_offset=offset)
