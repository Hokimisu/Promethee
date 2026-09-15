import copy

import pytest

from promethee.pose import validate_pose


def test_pose_returns_an_independent_observation(articulated_pose):
    validated = validate_pose(articulated_pose, [0, 0])
    assert validated == articulated_pose
    validated["positions"][0][0] = 1
    assert articulated_pose["positions"][0][0] == 0


@pytest.mark.parametrize("defect", ["count", "nan", "reflection", "scale", "root", "metadata"])
def test_pose_rejects_inconsistent_geometry(articulated_pose, defect):
    pose = copy.deepcopy(articulated_pose)
    if defect == "count":
        pose["positions"].pop()
    elif defect == "nan":
        pose["positions"][4][1] = float("nan")
    elif defect == "reflection":
        pose["rotations"][0][0][0] = -1
    elif defect == "scale":
        pose["rotations"][3][1][1] = 2
    elif defect == "root":
        pose["positions"][0][0] = 0.1
    else:
        pose["completed"] = True
    with pytest.raises(ValueError):
        validate_pose(pose, [0, 0])
