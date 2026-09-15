import hashlib
import math
import sqlite3

import pytest

from promethee.rendering import read_snapshot, rest_pose, world_to_xyz
from promethee.runtime import Runtime


@pytest.mark.parametrize("position", [[0, 0], [1, 0], [0, 1], [-2, 3]])
def test_floor_axes_and_distances(position):
    xyz = world_to_xyz(position, 0.4)
    assert xyz == (position[0], 0.4, position[1])
    assert math.dist(xyz, (0, 0.4, 0)) == math.dist(position, [0, 0])


def test_rest_rotation_preserves_bones_and_floor():
    # Tiny geometric fixture; the real Core skeleton is qualified separately in T06.
    skeleton = {"neutral_joints": [(0, 0, 0), (0, -1, 0), (0, 0, 1)]}
    pose = rest_pose(skeleton, [2, -3], math.pi / 2)
    assert pose[0] == (2, 1, -3)
    assert pose[1] == (2, 0, -3)
    assert pose[2] == pytest.approx((3, 1, -3))
    assert math.dist(pose[0], pose[2]) == pytest.approx(1)


def test_viewer_reopens_layout_without_writing(tmp_path):
    path = tmp_path / "world.sqlite3"
    runtime = Runtime(path)
    for i, position in enumerate(([1, 0], [-2, 3], [0, -4])):
        assert runtime.execute(
            f"new-{i}",
            {
                "kind": "spawn",
                "args": {"object_id": f"object-{i}", "asset": "chair", "position": position},
            },
        )["ok"]
    expected = runtime.snapshot()
    digest = hashlib.sha256(path.read_bytes()).digest()
    for _ in range(3):
        assert read_snapshot(path) == expected
    assert hashlib.sha256(path.read_bytes()).digest() == digest
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        read_snapshot(missing)
    assert not missing.exists()


@pytest.mark.parametrize("position,height", [([True, 0], 0), ([1], 0), ([0, 0], float("nan"))])
def test_invalid_coordinates(position, height):
    with pytest.raises(ValueError):
        world_to_xyz(position, height)
