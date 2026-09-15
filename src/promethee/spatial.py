"""Rigid object observations and Core hand attachments, without contact physics."""

import copy
import math

HANDS = {"RightHand": 10, "LeftHand": 16}  # Qualified cskel27 joint names.


def _vector(value, limit):
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(type(x) not in (int, float) or not math.isfinite(x) or abs(x) > limit for x in value)
    ):
        raise ValueError("Expected a bounded finite XYZ position in metres.")


def _rotation(matrix):
    if not isinstance(matrix, list) or len(matrix) != 3:
        raise ValueError("Expected a 3 by 3 rotation matrix.")
    for row in matrix:
        _vector(row, 1.00001)
    for i in range(3):
        for j in range(3):
            if abs(sum(matrix[i][k] * matrix[j][k] for k in range(3)) - int(i == j)) > 1e-5:
                raise ValueError("Object rotation must be orthonormal.")
    a, b, c = matrix
    determinant = (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )
    if abs(determinant - 1) > 1e-5:
        raise ValueError("Object rotation must preserve handedness.")


def _multiply(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def attachment_transform(attachment, pose):
    """Compute a rigid object's world transform from a validated articulated pose.

    The local transform is supplied by a contact-qualified controller. This
    function neither chooses an attachment nor proves that the hand touches it.
    """
    if not isinstance(attachment, dict) or set(attachment) != {"joint", "position", "rotation"}:
        raise ValueError("An attachment requires joint, local position and local rotation.")
    if not isinstance(attachment["joint"], str) or attachment["joint"] not in HANDS:
        raise ValueError("Only qualified Core hand joints can hold objects.")
    _vector(attachment["position"], 0.5)
    _rotation(attachment["rotation"])
    if not isinstance(pose, dict) or pose.get("skeleton") != "cskel27":
        raise ValueError("A hand attachment requires an observed Core pose.")
    joint = HANDS[attachment["joint"]]
    hand, rotation = pose["positions"][joint], pose["rotations"][joint]
    return {
        "position": [
            hand[i] + sum(rotation[i][k] * attachment["position"][k] for k in range(3))
            for i in range(3)
        ],
        "rotation": _multiply(rotation, attachment["rotation"]),
    }


def validate_spatial(value, floor_position, pose):
    if not isinstance(value, dict) or set(value) != {"position", "rotation", "attachment"}:
        raise ValueError("Spatial objects require position, rotation and attachment.")
    if pose is None:
        raise ValueError("Spatial objects require an articulated body observation.")
    _vector(value["position"], 5)
    _rotation(value["rotation"])
    if math.dist([value["position"][0], value["position"][2]], floor_position) > 1e-6:
        raise ValueError("Object floor position disagrees with its spatial position.")
    if value["attachment"] is not None:
        expected = attachment_transform(value["attachment"], pose)
        if math.dist(value["position"], expected["position"]) > 1e-5 or any(
            abs(value["rotation"][i][j] - expected["rotation"][i][j]) > 1e-5
            for i in range(3)
            for j in range(3)
        ):
            raise ValueError("Held object transform disagrees with its hand attachment.")
    return copy.deepcopy(value)


def follow_attachment(obj, pose):
    """Return a new object observation following an already established attachment."""
    from promethee.pose import validate_pose

    if not isinstance(pose, dict) or not isinstance(pose.get("positions"), list):
        raise ValueError("Expected an articulated pose.")
    # Validate dimensions before indexing the root.
    if len(pose["positions"]) != 27:
        raise ValueError("Expected 27 joint positions.")
    _vector(pose["positions"][0], 5)
    validate_pose(pose, [pose["positions"][0][0], pose["positions"][0][2]])
    if not isinstance(obj, dict) or not isinstance(obj.get("spatial"), dict):
        raise ValueError("Expected a spatial object.")
    attachment = obj["spatial"].get("attachment")
    transform = attachment_transform(attachment, pose)
    result = copy.deepcopy(obj)
    result["spatial"] = {**transform, "attachment": copy.deepcopy(attachment)}
    result["position"] = [transform["position"][0], transform["position"][2]]
    validate_spatial(result["spatial"], result["position"], pose)
    return result
