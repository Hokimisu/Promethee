"""Validated logical actions. A renderer/physics controller must replace instant transitions."""

import math
import re

from promethee.catalog import CATALOG


class ActionError(ValueError):
    """An action is invalid for the current world."""


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value):
        raise ActionError("Identifiers must use 1-64 lowercase letters, digits, '-' or '_'.")
    return value


def position(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ActionError("position must be [x, y] in floor-plane metres.")
    if any(type(v) not in (int, float) or abs(v) > 5 or not math.isfinite(v) for v in value):
        raise ActionError("Coordinates must be finite numbers between -5 and 5 metres.")
    return [float(v) for v in value]


def apply(world, action):
    """Mutate a candidate snapshot; the caller commits it only on success."""
    if not isinstance(action, dict) or set(action) != {"kind", "args"}:
        raise ActionError("An action must contain exactly 'kind' and 'args'.")
    kind, args = action["kind"], action["args"]
    fields = {
        "spawn": {"object_id", "asset", "position"},
        "move": {"position"},
        "write": {"object_id", "text"},
        "take": {"object_id"},
        "place": {"position"},
        "sit": {"object_id"},
        "stand": set(),
    }
    if not isinstance(kind, str) or kind not in fields:
        raise ActionError("Unknown action kind.")
    if not isinstance(args, dict) or set(args) != fields[kind]:
        raise ActionError(f"Expected arguments for {kind}: {sorted(fields[kind])}")

    avatar, objects = world["avatar"], world["objects"]

    def near(point):
        if math.dist(avatar["position"], point) > 1.0:
            raise ActionError("Target is out of reach (logical limit: 1 metre).")

    def get_object():
        object_id = identifier(args["object_id"])
        if object_id not in objects:
            raise ActionError(f"Unknown object: {object_id}")
        return object_id, objects[object_id]

    if kind == "spawn":
        object_id = identifier(args["object_id"])
        asset = args["asset"]
        if not isinstance(asset, str) or asset not in CATALOG:
            raise ActionError("Unknown catalog asset.")
        if object_id in objects:
            raise ActionError("Object already exists.")
        if len(objects) >= 32:
            raise ActionError("Room capacity reached (32 objects).")
        objects[object_id] = {"asset": asset, "position": position(args["position"])}
    elif kind == "move":
        if avatar["seated_on"]:
            raise ActionError("Stand before moving.")
        avatar["position"] = position(args["position"])
        if avatar["holding"]:
            objects[avatar["holding"]]["position"] = avatar["position"].copy()
    elif kind == "write":
        _, obj = get_object()
        if not CATALOG[obj["asset"]].get("write"):
            raise ActionError("Object is not writable.")
        near(obj["position"])
        if not isinstance(args["text"], str) or not 1 <= len(args["text"]) <= 500:
            raise ActionError("Sign text must contain 1-500 characters.")
        obj["text"] = args["text"]
    elif kind == "take":
        object_id, obj = get_object()
        if avatar["holding"]:
            raise ActionError("Hands are occupied.")
        if not CATALOG[obj["asset"]]["movable"] or avatar["seated_on"] == object_id:
            raise ActionError("Object cannot be picked up in this state.")
        near(obj["position"])
        avatar["holding"] = object_id
        obj["position"] = avatar["position"].copy()
    elif kind == "place":
        if not avatar["holding"]:
            raise ActionError("No held object.")
        point = position(args["position"])
        near(point)
        objects[avatar["holding"]]["position"] = point
        avatar["holding"] = None
    elif kind == "sit":
        object_id, obj = get_object()
        if not CATALOG[obj["asset"]].get("sit"):
            raise ActionError("Object has no sitting affordance.")
        if avatar["seated_on"] or avatar["holding"] == object_id:
            raise ActionError("Cannot sit in the current state.")
        near(obj["position"])
        avatar["seated_on"] = object_id
        avatar["position"] = obj["position"].copy()
        if avatar["holding"]:
            objects[avatar["holding"]]["position"] = avatar["position"].copy()
    elif kind == "stand":
        if not avatar["seated_on"]:
            raise ActionError("Avatar is already standing.")
        avatar["seated_on"] = None
