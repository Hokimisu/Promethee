"""Kinematic point attachment to explicit object surfaces, with conservative clearance.

No gravity, finger closure or compliant contact is simulated. Free objects stay
at their observed world transforms. These actions must be enabled explicitly.
"""

import copy
import math

from promethee.arm_reach import ARMS, reach_arm
from promethee.object_models import CONTACT_POINTS, OBJECT_MODELS
from promethee.spatial import follow_attachment

IDENTITY = [[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]]
HAND_ROTATION = [[-1.0, 0, 0], [0, 1.0, 0], [0, 0, -1.0]]


def bounds(obj):
    import numpy as np

    spatial = obj["spatial"]
    rotation = np.asarray(spatial["rotation"])
    low, high = np.full(3, np.inf), np.full(3, -np.inf)
    for part in OBJECT_MODELS[obj["asset"]]:
        center = np.asarray(spatial["position"]) + rotation @ part["center"]
        radius = np.sqrt((rotation**2) @ (np.asarray(part["size"]) / 2) ** 2)
        low, high = np.minimum(low, center - radius), np.maximum(high, center + radius)
    return low, high


def segment_hits_box(a, b, low, high):
    """Slab intersection, including endpoints; no geometry is modified."""
    first, last = 0.0, 1.0
    for axis in range(3):
        delta = b[axis] - a[axis]
        if abs(delta) < 1e-10:
            if not low[axis] <= a[axis] <= high[axis]:
                return False
        else:
            x, y = (low[axis] - a[axis]) / delta, (high[axis] - a[axis]) / delta
            first, last = max(first, min(x, y)), min(last, max(x, y))
            if first > last:
                return False
    return True


def check_clearance(observation):
    """Conservative object AABBs and body capsules; fingers and skin are excluded."""
    import numpy as np

    if observation.get("pose") is None:
        raise ValueError("Object interactions require an observed articulated body pose.")
    points = observation["pose"]["positions"]
    # Core's torso, head, legs, and upper/lower arms. The hand contact point is
    # intentionally not a finger-volume proxy; no finger contact is claimed.
    segments = [
        (0, 4, 0.12),
        (5, 6, 0.10),
        (19, 20, 0.06),
        (20, 21, 0.05),
        (23, 24, 0.06),
        (24, 25, 0.05),
        (8, 9, 0.035),
        (9, 10, 0.035),
        (14, 15, 0.035),
        (15, 16, 0.035),
    ]
    boxes = []
    for obj in observation["objects"].values():
        if obj["asset"] not in OBJECT_MODELS or "spatial" not in obj:
            raise ValueError("Object interactions require a known spatial visual model.")
        low, high = bounds(obj)
        if low[1] < -1e-5 or np.any(low[[0, 2]] < -5) or np.any(high[[0, 2]] > 5):
            raise ValueError("Object geometry intersects the floor or leaves the room.")
        if any(
            np.all(low < other_high) and np.all(high > other_low) for other_low, other_high in boxes
        ):
            raise ValueError("Object clearance boxes overlap.")
        for a, b, radius in segments:
            if segment_hits_box(points[a], points[b], low - radius, high + radius):
                raise ValueError("Object clearance intersects a body segment.")
        boxes.append((low, high))


def _poses(values):
    return [
        {"skeleton": "cskel27", "positions": p.tolist(), "rotations": r.tolist()}
        for p, r in zip(values["posed_joints"], values["global_rot_mats"], strict=True)
    ]


def prepare_object_action(observation, skeleton, action):
    """Preflight the whole trajectory and return observed snapshots for playback."""
    import numpy as np

    from promethee.world import validate_observation

    kind, args = action["kind"], action["args"]
    current = copy.deepcopy(observation)
    if kind == "spawn":
        if args["asset"] not in OBJECT_MODELS or len(args["position"]) != 3:
            raise ValueError("Spatial spawning requires a known model and an XYZ position.")
        point = args["position"]
        current["objects"][args["object_id"]] = {
            "asset": args["asset"],
            "position": [point[0], point[2]],
            "spatial": {"position": point, "rotation": IDENTITY, "attachment": None},
        }
        check_clearance(current)
        return [validate_observation(current)]
    if kind == "take":
        object_id = args["object_id"]
        obj = current["objects"][object_id]
        if obj["asset"] not in CONTACT_POINTS:
            raise ValueError("No contact geometry is defined for this object model.")
        if "spatial" not in obj or obj["spatial"]["attachment"] is not None:
            raise ValueError("Taking requires an unattached spatial object.")
        candidates = []
        failures = []
        for side, sign in (("right", -1), ("left", 1)):
            try:
                # An explicit surface point from this object's geometry.
                contact = (
                    np.array(obj["spatial"]["position"])
                    + np.array(obj["spatial"]["rotation"]) @ CONTACT_POINTS[obj["asset"]][side]
                )
                rotation = np.array(obj["spatial"]["rotation"]) @ HAND_ROTATION
                palm = np.array([sign * 0.045, 0, 0])
                target = contact - rotation @ palm
                first = _poses(
                    reach_arm(
                        current["pose"],
                        skeleton,
                        target.tolist(),
                        side=side,
                        hand_rotation=rotation,
                    )
                )
                wrist = skeleton["joint_names"].index(ARMS[side][2])
                achieved = (
                    np.array(first[-1]["positions"][wrist])
                    + np.array(first[-1]["rotations"][wrist]) @ palm
                )
                if np.linalg.norm(achieved - contact) > 0.001:
                    raise ValueError("Hand contact point did not reach the object surface.")
                hand = np.array(first[-1]["rotations"][wrist])
                attachment = {
                    "joint": ARMS[side][2],
                    "position": (hand.T @ (np.array(obj["spatial"]["position"]) - target)).tolist(),
                    "rotation": (hand.T @ obj["spatial"]["rotation"]).tolist(),
                }
                lift = _poses(
                    reach_arm(
                        first[-1],
                        skeleton,
                        (target + [0, 0.06, 0]).tolist(),
                        side=side,
                        frames=31,
                        hand_rotation=rotation,
                    )
                )
                frames = []
                for index, pose in enumerate(first + lift[1:]):
                    value = copy.deepcopy(current)
                    value["pose"] = pose
                    if index >= len(first) - 1:
                        value["avatar"]["holding"] = object_id
                        value["objects"][object_id]["spatial"]["attachment"] = attachment
                        value["objects"][object_id] = follow_attachment(
                            value["objects"][object_id], pose
                        )
                    check_clearance(value)
                    frames.append(validate_observation(value))
                distance = math.dist(current["pose"]["positions"][wrist], target)
                candidates.append((distance, frames))
            except ValueError as exc:
                failures.append(f"{side}: {exc}")
                continue
        if not candidates:
            raise ValueError(
                "Neither hand has a reachable, clear approach and lift. " + "; ".join(failures)
            )
        return min(candidates, key=lambda item: item[0])[1]
    if kind == "place":
        if len(args["position"]) != 3:
            raise ValueError("Spatial placement requires an XYZ object position.")
        object_id = current["avatar"]["holding"]
        obj = current["objects"][object_id]
        attachment = obj["spatial"]["attachment"]
        side = "right" if attachment["joint"] == "RightHand" else "left"
        wrist = skeleton["joint_names"].index(attachment["joint"])
        rotation = np.array(current["pose"]["rotations"][wrist])
        target = np.array(args["position"]) - rotation @ attachment["position"]
        poses = _poses(
            reach_arm(current["pose"], skeleton, target.tolist(), side=side, hand_rotation=rotation)
        )
        frames = []
        for index, pose in enumerate(poses):
            value = copy.deepcopy(current)
            value["pose"] = pose
            value["objects"][object_id] = follow_attachment(obj, pose)
            if index == len(poses) - 1:
                if (
                    math.dist(value["objects"][object_id]["spatial"]["position"], args["position"])
                    > 0.001
                ):
                    raise ValueError("Held object missed its placement target.")
                value["avatar"]["holding"] = None
                value["objects"][object_id]["spatial"]["attachment"] = None
            check_clearance(value)
            frames.append(validate_observation(value))
        return frames
    raise ValueError("Unsupported spatial interaction.")
