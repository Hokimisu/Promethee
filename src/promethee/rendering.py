"""Read-only snapshots and the single logical-plane to Y-up conversion."""

import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path

from promethee.migrations import check_version, read_world


def world_to_xyz(position, height=0.0):
    if len(position) != 2:
        raise ValueError("Expected a logical [x, y] position.")
    values = (position[0], height, position[1])
    if any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
        for v in values
    ):
        raise ValueError("Coordinates must be finite numbers.")
    return tuple(float(v) for v in values)


def read_snapshot(path):
    """Never create, migrate, recover, or acquire a controller for the viewed world."""
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=2)) as conn:
        state = read_world(conn)
        check_version(state)
        return state


def load_skeleton(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    names, parents, joints = data["joint_names"], data["parents"], data["neutral_joints"]
    if data["skeleton"] != "cskel27" or len(names) != 27 or len(set(names)) != 27:
        raise ValueError("Expected the 27-joint Core export from T02.")
    if len(parents) != 27 or len(joints) != 27 or parents[0] != -1:
        raise ValueError("Invalid Core hierarchy.")
    for i, (parent, joint) in enumerate(zip(parents, joints, strict=True)):
        if type(parent) is not int or (i > 0 and not 0 <= parent < i):
            raise ValueError("Invalid parent index.")
        if len(joint) != 3 or any(not math.isfinite(v) for v in joint):
            raise ValueError("Invalid neutral joint.")
    return data


def rest_pose(skeleton, position, heading=0.0):
    """Diagnostic neutral pose, not an observed avatar posture or physical equilibrium."""
    if not math.isfinite(heading):
        raise ValueError("Heading must be finite.")
    neutral = skeleton["neutral_joints"]
    offset = world_to_xyz(position, -min(j[1] for j in neutral))
    c, s = math.cos(heading), math.sin(heading)
    return [
        (c * x + s * z + offset[0], y + offset[1], -s * x + c * z + offset[2])
        for x, y, z in neutral
    ]
