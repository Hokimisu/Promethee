"""Validated logical actions. A renderer/physics controller must replace instant transitions."""

import copy
import math
import re

from promethee.catalog import CATALOG
from promethee.pose import validate_pose
from promethee.spatial import validate_spatial

ACTION_FIELDS = {
    "spawn": {"object_id", "asset", "position"},
    "move": {"position"},
    "write": {"object_id", "text"},
    "take": {"object_id"},
    "place": {"position"},
    "sit": {"object_id"},
    "stand": set(),
}
BODY_ACTION_FIELDS = {**ACTION_FIELDS, "posture": {"name"}}
POSTURES = {"standing", "arms_raised"}


def validate_body_action(world, action):
    """Check an intention without applying it to the authoritative world."""
    if isinstance(action, dict) and action.get("kind") in {"spawn", "place"}:
        args = action.get("args")
        point = args.get("position") if isinstance(args, dict) else None
        if isinstance(point, list) and len(point) == 3:
            if any(
                type(x) not in (int, float) or not math.isfinite(x) or abs(x) > 5 for x in point
            ):
                raise ActionError(
                    "Spatial positions must be finite XYZ coordinates within [-5, 5]."
                )
            preview = copy.deepcopy(action)
            preview["args"]["position"] = [point[0], point[2]]
            apply(copy.deepcopy(world), preview)
            return  # The actual controller checks geometry and anatomical reach.
    if isinstance(action, dict) and action.get("kind") == "posture":
        if set(action) != {"kind", "args"}:
            raise ActionError("An action must contain exactly 'kind' and 'args'.")
        args = action["args"]
        if not isinstance(args, dict) or set(args) != {"name"}:
            raise ActionError("Expected posture arguments: ['name']")
        if not isinstance(args["name"], str) or args["name"] not in POSTURES:
            raise ActionError("Unknown posture.")
        if world["avatar"]["holding"] or world["avatar"]["seated_on"]:
            raise ActionError("Posture changes require empty hands and no occupied support.")
        return
    apply(copy.deepcopy(world), action)


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
    fields = ACTION_FIELDS
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


def validate_observation(observation):
    """Validate observations; only logical test drivers may omit an articulated pose."""
    if not isinstance(observation, dict) or not {"avatar", "objects"} <= set(observation) <= {
        "avatar",
        "objects",
        "pose",
    }:
        raise ActionError("An observation requires avatar, objects and optionally pose.")
    observed = copy.deepcopy(observation)
    avatar, objects = observed["avatar"], observed["objects"]
    if not isinstance(avatar, dict) or set(avatar) != {"position", "holding", "seated_on"}:
        raise ActionError("Invalid observed avatar fields.")
    avatar["position"] = position(avatar["position"])
    try:
        observed["pose"] = (
            validate_pose(observed["pose"], avatar["position"])
            if observed.get("pose") is not None
            else None
        )
    except ValueError as exc:
        raise ActionError(str(exc)) from exc
    if not isinstance(objects, dict) or len(objects) > 32:
        raise ActionError("Invalid observed objects.")
    for object_id, obj in objects.items():
        identifier(object_id)
        if not isinstance(obj, dict) or not {"asset", "position"} <= set(obj) <= {
            "asset",
            "position",
            "text",
            "spatial",
        }:
            raise ActionError("Invalid observed object fields.")
        if not isinstance(obj["asset"], str) or obj["asset"] not in CATALOG:
            raise ActionError("Unknown observed asset.")
        obj["position"] = position(obj["position"])
        if "spatial" in obj:
            try:
                obj["spatial"] = validate_spatial(obj["spatial"], obj["position"], observed["pose"])
            except ValueError as exc:
                raise ActionError(str(exc)) from exc
            attached = obj["spatial"]["attachment"] is not None
            if attached != (avatar["holding"] == object_id):
                raise ActionError("Hand attachment and held object reference disagree.")
        if "text" in obj and (
            not CATALOG[obj["asset"]].get("write")
            or not isinstance(obj["text"], str)
            or not 1 <= len(obj["text"]) <= 500
        ):
            raise ActionError("Invalid observed text.")
    for field, capability in (("holding", "movable"), ("seated_on", "sit")):
        target = avatar[field]
        if target is not None:
            identifier(target)
            if target not in objects or not CATALOG[objects[target]["asset"]].get(capability):
                raise ActionError(f"Invalid observed {field} reference.")
            if field == "holding" and "spatial" in objects[target]:
                continue  # The full hand transform was checked above, not the hips projection.
            if math.dist(avatar["position"], objects[target]["position"]) > 1e-6:
                raise ActionError(f"Observed {field} object is detached from avatar.")
    if avatar["holding"] is not None and avatar["holding"] == avatar["seated_on"]:
        raise ActionError("An avatar cannot hold its occupied support.")
    return observed
