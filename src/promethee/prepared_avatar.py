"""Validate offline appearance records before any controller or world mutation.

This checks provenance, pose correspondence and attached-hand kinematics. The
producer separately measures the VRM skin; this is not a physics validator.
"""

import hashlib
import json
import math
from pathlib import Path

from promethee.avatar_reach import PIXIV_SHA256, PixivArmReach
from promethee.avatar_rotation import normalized_core_rotation, quaternion_matrix
from promethee.pose import validate_pose

EXTRA_BONES = {
    "neck": "Neck",
    "head": "Head",
    "rightUpperLeg": "RightUpLeg",
    "rightLowerLeg": "RightLeg",
    "rightFoot": "RightFoot",
    "rightToes": "RightToeBase",
    "leftUpperLeg": "LeftUpLeg",
    "leftLowerLeg": "LeftLeg",
    "leftFoot": "LeftFoot",
    "leftToes": "LeftToeBase",
}
MAX_BYTES = 32 * 1024 * 1024


def _number(value):
    return type(value) in {int, float} and math.isfinite(value)


def _rotation(q):
    if (
        not isinstance(q, list)
        or len(q) != 4
        or not all(map(_number, q))
        or abs(math.hypot(*q) - 1) > 1e-6
    ):
        raise ValueError("Invalid prepared avatar quaternion.")
    return quaternion_matrix(q)


def load_prepared_poses(path, motion_bytes):
    """Return checked JSON records bound to the exact supplied motion document.

    No paths from the artifact are opened and no state is written. Callers must
    provide the document they submitted to the local preparation process.
    """
    import numpy as np

    with Path(path).open("rb") as stream:
        content = stream.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES or len(motion_bytes) > MAX_BYTES:
        raise ValueError("Prepared avatar input exceeds 32 MiB.")
    artifact, document = json.loads(content), json.loads(motion_bytes)
    reach = PixivArmReach()
    profile = reach.profile
    fields = {
        "version",
        "avatar_sha256",
        "motion_sha256",
        "scale",
        "mode",
        "aligned_hands",
        "frames",
    }
    if (
        not isinstance(artifact, dict)
        or set(artifact) != fields
        or type(artifact["version"]) is not int
        or artifact["version"] != 1
        or artifact["avatar_sha256"] != PIXIV_SHA256
        or artifact["motion_sha256"] != hashlib.sha256(motion_bytes).hexdigest()
        or not _number(artifact["scale"])
        or abs(artifact["scale"] - profile["scale"]) > 1e-8
        or artifact["mode"] not in ("--plant", "--settle")
    ):
        raise ValueError("Prepared avatar provenance or format mismatch.")
    if (
        not isinstance(document, dict)
        or document.get("fps") != 20
        or document.get("avatar_profile") != profile
        or not isinstance(document.get("frames"), list)
        or not 1 <= len(document["frames"]) <= 1200
        or not isinstance(artifact["frames"], list)
        or len(artifact["frames"]) != len(document["frames"])
    ):
        raise ValueError("Prepared avatar and Core frame counts or profile differ.")
    skeleton = document["skeleton"]
    names = skeleton["joint_names"]
    bones = {name: bone["source"] for name, bone in profile["bones"].items()} | EXTRA_BONES
    if (
        len(names) != 27
        or len(set(names)) != 27
        or names[0] != "Hips"
        or not set(bones.values()).issubset(names)
        or abs(-min(p[1] for p in skeleton["neutral_joints"]) - profile["core_hip_height"]) > 1e-6
    ):
        raise ValueError("Unexpected prepared avatar skeleton.")
    objects = document.get("objects", [{} for _ in document["frames"]])
    if not isinstance(objects, list) or len(objects) != len(document["frames"]):
        raise ValueError("Prepared avatar object frame count differs.")
    expected_hands = {
        obj["spatial"]["attachment"]["joint"]
        for frame in objects
        for obj in frame.values()
        if obj["spatial"].get("attachment") is not None
    }
    hands = artifact["aligned_hands"]
    if (
        not isinstance(hands, list)
        or any(h not in ("RightHand", "LeftHand") for h in hands)
        or len(hands) != len(set(hands))
        or set(hands) != expected_hands
    ):
        raise ValueError("Prepared avatar attachment hands differ.")
    mutable = set()
    if artifact["mode"] == "--plant":
        contacts = document.get("foot_contacts")
        if (
            not isinstance(contacts, list)
            or len(contacts) != len(document["frames"])
            or any(
                not isinstance(flags, list)
                or len(flags) != 4
                or any(type(flag) is not bool for flag in flags)
                or not any(flags)
                for flags in contacts
            )
        ):
            raise ValueError("Prepared avatar planting requires archived support flags.")
        mutable.update(set(EXTRA_BONES) - {"neck", "head"})
    for hand in hands:
        side = "right" if hand == "RightHand" else "left"
        mutable.update({side + "UpperArm", side + "LowerArm"})
    previous_offset = None
    for source, prepared in zip(document["frames"], artifact["frames"], strict=True):
        validate_pose(source, [source["positions"][0][0], source["positions"][0][2]])
        if (
            not isinstance(prepared, dict)
            or set(prepared) != {"root_y_offset", "rotations"}
            or not _number(prepared["root_y_offset"])
            or abs(prepared["root_y_offset"]) > 0.05
            or not isinstance(prepared["rotations"], dict)
            or set(prepared["rotations"]) != set(bones)
        ):
            raise ValueError("Invalid prepared avatar pose.")
        offset = prepared["root_y_offset"]
        if previous_offset is not None and abs(offset - previous_offset) > 0.015 + 1e-8:
            raise ValueError("Prepared avatar root step exceeds 15 mm.")
        previous_offset = offset
        rotations = {name: _rotation(q) for name, q in prepared["rotations"].items()}
        normalized = [normalized_core_rotation(rows) for rows in source["rotations"]]
        for name in set(bones) - mutable:
            if np.max(np.abs(rotations[name] - normalized[names.index(bones[name])])) > 1e-5:
                raise ValueError("Prepared avatar changed an unadapted Core rotation.")
        for hand in hands:
            reach.check(source, skeleton, hand, root_y_offset=offset)
            side = "right" if hand == "RightHand" else "left"
            chain = [
                "hips",
                "spine",
                "chest",
                "upperChest",
                side + "Shoulder",
                side + "UpperArm",
                side + "LowerArm",
                side + "Hand",
            ]
            position = np.array(source["positions"][0], dtype=float)
            position[1] += offset
            for parent, child in zip(chain[:-1], chain[1:], strict=True):
                rest = profile["bones"]
                delta = (
                    np.array(rest[child]["rest_position"]) - rest[parent]["rest_position"]
                ) * profile["scale"]
                position += rotations[parent] @ delta
            if np.linalg.norm(position - source["positions"][names.index(hand)]) > 1e-5:
                raise ValueError("Prepared avatar wrist misses the observed Core target.")
    return artifact
