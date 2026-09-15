"""Validation of observed Core poses in metres, Y-up, with global rotation matrices."""

import copy
import math


def _numbers(values, size):
    if not isinstance(values, list) or len(values) != size:
        raise ValueError("Invalid pose dimensions.")
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in values):
        raise ValueError("Pose values must be finite numbers.")


def validate_pose(pose, floor_position):
    if not isinstance(pose, dict) or set(pose) != {"skeleton", "positions", "rotations"}:
        raise ValueError("A pose requires skeleton, positions and rotations.")
    if pose["skeleton"] != "cskel27":
        raise ValueError("Only the qualified Core skeleton is supported.")
    positions, rotations = pose["positions"], pose["rotations"]
    if not isinstance(positions, list) or len(positions) != 27:
        raise ValueError("Expected 27 joint positions.")
    if not isinstance(rotations, list) or len(rotations) != 27:
        raise ValueError("Expected 27 joint rotations.")
    for point in positions:
        _numbers(point, 3)
        if max(abs(v) for v in point) > 100:
            raise ValueError("Pose coordinate exceeds the supported range.")
    for matrix in rotations:
        if not isinstance(matrix, list) or len(matrix) != 3:
            raise ValueError("Expected 3 by 3 global rotations.")
        for row in matrix:
            _numbers(row, 3)
        for i in range(3):
            for j in range(3):
                dot = sum(matrix[i][k] * matrix[j][k] for k in range(3))
                if abs(dot - int(i == j)) > 0.01:
                    raise ValueError("Rotation matrix is not orthonormal.")
        a, b, c = matrix
        determinant = (
            a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0])
        )
        if abs(determinant - 1) > 0.01:
            raise ValueError("Rotation must preserve handedness.")
    if math.dist([positions[0][0], positions[0][2]], floor_position) > 0.0001:
        raise ValueError("Observed hips and floor position disagree.")
    return copy.deepcopy(pose)
