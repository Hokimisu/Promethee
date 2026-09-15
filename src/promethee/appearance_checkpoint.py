"""CPU-only persistence contract for a previously prepared visible pose.

This binds a record to its observed Core pose. Geometry and reach are checked
by the preparation pipeline, not re-established by the storage envelope.
"""

import copy
import hashlib
import json
import math

from promethee.avatar_reach import PIXIV_SHA256, load_profile
from promethee.prepared_avatar import EXTRA_BONES


def pose_digest(pose):
    payload = json.dumps(pose, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_appearance(value, pose):
    if value is None:
        return None
    profile = load_profile()
    if (
        pose is None
        or not isinstance(value, dict)
        or set(value)
        != {
            "version",
            "avatar_sha256",
            "core_pose_sha256",
            "scale",
            "mode",
            "aligned_hands",
            "frame",
        }
        or type(value["version"]) is not int
        or value["version"] != 1
        or value["avatar_sha256"] != PIXIV_SHA256
        or value["core_pose_sha256"] != pose_digest(pose)
        or type(value["scale"]) not in (int, float)
        or not math.isfinite(value["scale"])
        or abs(value["scale"] - profile["scale"]) > 1e-8
        or value["mode"] not in ("--settle", "--plant")
    ):
        raise ValueError("Appearance checkpoint does not match its Core pose or avatar.")
    hands = value["aligned_hands"]
    if (
        not isinstance(hands, list)
        or any(h not in ("RightHand", "LeftHand") for h in hands)
        or len(hands) != len(set(hands))
    ):
        raise ValueError("Invalid checkpoint hand alignment.")
    frame = value["frame"]
    if (
        not isinstance(frame, dict)
        or set(frame) != {"root_y_offset", "rotations"}
        or type(frame["root_y_offset"]) not in (int, float)
        or not math.isfinite(frame["root_y_offset"])
        or abs(frame["root_y_offset"]) > 0.05
        or not isinstance(frame["rotations"], dict)
        or set(frame["rotations"]) != set(profile["bones"]) | set(EXTRA_BONES)
    ):
        raise ValueError("Invalid appearance checkpoint frame.")
    for rotation in frame["rotations"].values():
        if (
            not isinstance(rotation, list)
            or len(rotation) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in rotation)
            or abs(math.hypot(*rotation) - 1) > 1e-6
        ):
            raise ValueError("Invalid appearance checkpoint rotation.")
    return copy.deepcopy(value)


def appearance_checkpoint(artifact, index, pose):
    """Select one frame from the artifact already validated for the submitted motion."""
    if type(index) is not int or not 0 <= index < len(artifact["frames"]):
        raise ValueError("Invalid prepared appearance frame index.")
    checkpoint = {
        key: copy.deepcopy(artifact[key])
        for key in ("version", "avatar_sha256", "scale", "mode", "aligned_hands")
    }
    checkpoint.update(
        core_pose_sha256=pose_digest(pose), frame=copy.deepcopy(artifact["frames"][index])
    )
    return validate_appearance(checkpoint, pose)
