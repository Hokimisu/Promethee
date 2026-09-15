"""Check T06 against exported Core geometry and an existing world, without writes."""

import argparse
import hashlib
import json
import math

import numpy as np

from promethee.rendering import load_skeleton, read_snapshot, rest_pose
from promethee.viewer import load_motion


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--skeleton", required=True)
    parser.add_argument("--motion", required=True)
    args = parser.parse_args()
    from pathlib import Path

    before = hashlib.sha256(Path(args.database).read_bytes()).hexdigest()
    world = read_snapshot(args.database)
    assert read_snapshot(args.database) == world
    skeleton = load_skeleton(args.skeleton)
    rest = np.asarray(rest_pose(skeleton, [0, 0]))
    right = np.asarray(rest_pose(skeleton, [1, 0]))
    forward = np.asarray(rest_pose(skeleton, [0, 1]))
    np.testing.assert_allclose(right - rest, np.tile([1, 0, 0], (27, 1)), atol=1e-12)
    np.testing.assert_allclose(forward - rest, np.tile([0, 0, 1], (27, 1)), atol=1e-12)
    turned = np.asarray(rest_pose(skeleton, [0, 0], math.pi / 2))
    root = turned[0]
    relative = rest - rest[0]
    np.testing.assert_allclose(turned - root, relative[:, [2, 1, 0]] * [1, 1, -1], atol=1e-12)
    assert abs(rest[:, 1].min()) < 1e-12
    positions, fps = load_motion(args.motion, np)
    with np.load(args.motion, allow_pickle=False) as original:
        np.testing.assert_array_equal(positions, original["posed_joints"])
    assert hashlib.sha256(Path(args.database).read_bytes()).hexdigest() == before
    print(
        json.dumps(
            {
                "read_only": True,
                "world_id": world["world_id"],
                "objects": {key: obj["position"] for key, obj in world["objects"].items()},
                "joint_count": len(rest),
                "neutral_height_m": float(np.ptp(rest[:, 1])),
                "frames": len(positions),
                "fps": fps,
                "coordinates_preserved": True,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
