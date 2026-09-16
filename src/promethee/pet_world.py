"""Trusted sandbox interventions and object physics, committed with observations.

This is a controller extension, never an agent tool. The optional ``sandbox``
checkpoint is installed explicitly by the pet controller in interactive worlds.
External events use the existing durable event log, not successful body actions.
"""

import copy
import json
import math
from uuid import uuid4

from promethee.appearance_checkpoint import pose_digest
from promethee.execution import command_revision, timestamp
from promethee.migrations import read_world
from promethee.object_actions import IDENTITY, check_clearance
from promethee.object_models import OBJECT_MODELS
from promethee.pet_physics import MAX_SPEED, step_ball
from promethee.runtime import encode
from promethee.spatial import follow_attachment
from promethee.world import ActionError, identifier, validate_observation

KINDS = [
    "spawn",
    "grab_begin",
    "grab_end",
    "grab_cancel",
    "relocate_avatar",
    "relocate_object",
    "throw",
]
GRAB_SECONDS = 30


def catalog():
    return {
        "object_models": sorted(OBJECT_MODELS),
        "object_geometry": copy.deepcopy(OBJECT_MODELS),
        "supported_interventions": KINDS.copy(),
        "bounds": {"min": [-4.5, 0, -4.5], "max": [4.5, 5, 4.5]},
    }


def vector(value, size, limit=4.5):
    if (
        not isinstance(value, list)
        or len(value) != size
        or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > limit for v in value)
    ):
        raise ActionError(f"Expected {size} finite coordinates within +/-{limit}.")
    return list(value)


def object_position(obj, value):
    point = vector(value, 3, 5)
    rotation = obj["spatial"]["rotation"][1]
    ranges = [
        (
            sum(rotation[i] * part["center"][i] for i in range(3)),
            math.sqrt(sum((rotation[i] * part["size"][i] / 2) ** 2 for i in range(3))),
        )
        for part in OBJECT_MODELS[obj["asset"]]
    ]
    minimum = -min(center - radius for center, radius in ranges)
    maximum = 5 - max(center + radius for center, radius in ranges)
    if not minimum - 1e-6 <= point[1] <= maximum + 1e-6 or max(abs(point[0]), abs(point[2])) > 4.5:
        raise ActionError("Object position must stay above the floor and inside the room.")
    point[1] = max(minimum, min(maximum, point[1]))
    obj["position"] = [point[0], point[2]]
    obj["spatial"]["position"] = point


def relocate_avatar(observation, value):
    point = vector(value, 2, 4.2)
    previous = observation["avatar"]["position"]
    delta = [point[0] - previous[0], 0, point[1] - previous[1]]
    for joint in observation["pose"]["positions"]:
        for axis in (0, 2):
            joint[axis] += delta[axis]
    observation["avatar"]["position"] = point
    held = observation["avatar"]["holding"]
    if held:
        observation["objects"][held] = follow_attachment(
            observation["objects"][held], observation["pose"]
        )
    if observation.get("appearance") is not None:
        # A floor-plane rigid translation preserves the prepared rotations,
        # foot heights, scale and hand alignment. No retargeting is invented.
        observation["appearance"]["core_pose_sha256"] = pose_digest(observation["pose"])


class PetWorld:
    def __init__(self, service, handle):
        self.service, self.handle = service, handle
        with service._transaction() as (conn, now):
            self._owned(conn, now)
            world = read_world(conn)
            if world["data_origin"] != "session" or world["session_kind"] != "interactive":
                raise ActionError("Pet life requires its own interactive world.")
            if "sandbox" not in world:
                world["sandbox"] = {
                    "version": 1,
                    "grab": None,
                    "flights": {},
                    "recent_events": [],
                    "suspended": True,
                    "object_models": sorted(OBJECT_MODELS),
                    "bounds": catalog()["bounds"],
                    "physics": "Ball gravity and static collision proxies; no body dynamics.",
                    "object_interactions": (
                        "Arm reach only: no floor pickup from standing; "
                        "place held objects before locomotion."
                    ),
                }
                self._save(conn, world)
            elif world["sandbox"].get("version") != 1:
                raise ActionError("Unsupported pet checkpoint version.")
            if not world["sandbox"].get("suspended", True):
                world["sandbox"]["suspended"] = True
                self._save(conn, world)
            # A browser lease from a previous controller cannot retain the body.
            if world["sandbox"]["grab"]:
                world["sandbox"]["grab"] = None
                self._event(conn, world, "grab_released", {"reason": "controller_restart"}, now)
                self._save(conn, world)

    def _owned(self, conn, now):
        control = self.service._owned(conn, self.handle.session_id, now)
        if control is None:
            raise ActionError("The sandbox controller no longer owns this world.")
        return control

    @staticmethod
    def _save(conn, world):
        world["revision"] += 1
        conn.execute("UPDATE world SET data=? WHERE id=1", (encode(world),))

    @staticmethod
    def _event(conn, world, kind, details, now, *, request_id=None, envelope=None, result=None):
        event = {"kind": kind, "recorded_at": timestamp(now), **details}
        if envelope is not None:
            event.update(envelope=envelope, result=result)
        conn.execute(
            "INSERT INTO execution_events(request_id,data) VALUES (?,?)",
            (request_id or "pet-event-" + uuid4().hex, encode(event)),
        )
        world["sandbox"]["recent_events"] = [
            *world["sandbox"]["recent_events"],
            {key: value for key, value in event.items() if key not in {"envelope", "result"}},
        ][-12:]

    def apply(self, envelope, observation, stop):
        """Validate before stopping; stop+observe+event+request commit on one owner tick.

        ``stop`` invalidates all local playback/futures and must not access SQLite.
        An identical replay returns its historical result without stopping anything.
        """
        if not isinstance(envelope, dict) or set(envelope) != {
            "request_id",
            "expected_command_revision",
            "action",
        }:
            raise ActionError(
                "Intervention requires request_id, expected_command_revision, action."
            )
        rid = envelope["request_id"]
        identifier(rid)
        expected = envelope["expected_command_revision"]
        if type(expected) is not int or expected < 0:
            raise ActionError("Expected command revision must be a non-negative integer.")
        action = envelope["action"]
        if not isinstance(action, dict) or set(action) != {"kind", "args"}:
            raise ActionError("Intervention action requires kind and args.")
        kind, args = action["kind"], action["args"]
        if kind not in KINDS or not isinstance(args, dict):
            raise ActionError("Unknown sandbox intervention.")
        with self.service._transaction() as (conn, now):
            control = self._owned(conn, now)
            previous = conn.execute(
                "SELECT data FROM execution_events WHERE request_id=? ORDER BY seq LIMIT 1", (rid,)
            ).fetchone()
            if previous:
                saved = json.loads(previous[0])
                if saved.get("envelope") != envelope or "result" not in saved:
                    raise ActionError("Request ID reused with a different envelope.")
                return {**saved["result"], "replayed": True}
            if conn.execute("SELECT 1 FROM commands WHERE request_id=?", (rid,)).fetchone():
                raise ActionError("Request ID already belongs to a logical command.")
            world = read_world(conn)
            state = world["sandbox"]
            ending = kind in {"grab_end", "grab_cancel"}
            # A pointer takes ownership of an identified current target, not of
            # an old pose. Idle/body/physics frames may advance during hit testing.
            if not ending and kind != "grab_begin" and expected != command_revision(world):
                raise ActionError("revision_conflict: read the world before intervening.")
            if world["body"]["status"] != "confirmed":
                raise ActionError("Body is not ready for manipulation.")
            if state["grab"] and not ending:
                raise ActionError("Another pointer already holds the scene.")
            candidate = copy.deepcopy(observation)
            effective = kind
            if ending:
                grab = state["grab"]
                if not grab or args.get("grab_id") != grab["grab_id"] or now >= grab["expires_at"]:
                    raise ActionError("Grab is missing, expired or owned by another pointer.")
                allowed = (
                    {"grab_id"} if kind == "grab_cancel" else {"grab_id", "position", "velocity"}
                )
                if not set(args) <= allowed or (kind == "grab_end" and "position" not in args):
                    raise ActionError("Invalid grab completion fields.")
                if kind == "grab_end":
                    effective = (
                        "relocate_avatar" if grab["target"] == "avatar" else "relocate_object"
                    )
                    args = {**args, "object_id": grab.get("object_id")}
                state["grab"] = None
            if kind == "grab_begin":
                if set(args) not in ({"target"}, {"target", "object_id"}):
                    raise ActionError("Invalid grab target fields.")
                target = args["target"]
                if target not in {"avatar", "object"}:
                    raise ActionError("Grab target must be avatar or object.")
                if target == "object":
                    self._object(candidate, args.get("object_id"))
                elif "object_id" in args:
                    raise ActionError("Avatar grab cannot name an object.")
                state["grab"] = {
                    "grab_id": rid,
                    **args,
                    "expires_at": now + GRAB_SECONDS,
                }
                if target == "object":
                    state["flights"].pop(args["object_id"], None)
            elif effective == "spawn":
                if set(args) != {"model", "position"} or args["model"] not in OBJECT_MODELS:
                    raise ActionError("Choose a prepared object model and XYZ position.")
                oid = "object-" + uuid4().hex
                obj = {
                    "asset": args["model"],
                    "position": [0, 0],
                    "spatial": {
                        "position": [0, 0, 0],
                        "rotation": copy.deepcopy(IDENTITY),
                        "attachment": None,
                    },
                }
                object_position(obj, args["position"])
                candidate["objects"][oid] = obj
            elif effective == "relocate_avatar":
                if kind == "relocate_avatar" and set(args) != {"position"}:
                    raise ActionError("Avatar relocation requires a floor position.")
                if "velocity" in args:
                    raise ActionError("Avatar throwing is not implemented.")
                relocate_avatar(candidate, args["position"])
            elif effective in {"relocate_object", "throw"}:
                allowed = (
                    {"object_id", "position"}
                    if effective == "relocate_object"
                    else {"object_id", "velocity"}
                )
                if not ending and set(args) != allowed:
                    raise ActionError("Invalid object intervention fields.")
                oid = args["object_id"]
                obj = self._object(candidate, oid)
                if effective == "relocate_object":
                    object_position(obj, args["position"])
                state["flights"].pop(oid, None)
                if "velocity" in args:
                    velocity = vector(args["velocity"], 3, MAX_SPEED)
                    if obj["asset"] != "ball" or math.hypot(*velocity) > MAX_SPEED:
                        raise ActionError("Only balls can be thrown, at up to 12 m/s.")
                    state["flights"][oid] = {"velocity": velocity, "contacts": [], "source": "user"}
            candidate = validate_observation(candidate)
            try:
                check_clearance(candidate)
            except ValueError as exc:
                raise ActionError(str(exc)) from exc
            stop()
            for item in self.service._active(conn):
                item["status"] = "interrupted"
                item["observation"] = copy.deepcopy(observation)
                item["observed_at"] = timestamp(now)
                item["error"] = {
                    "code": "external_intervention",
                    "message": "Stopped by an external intervention.",
                }
                self.service._record(conn, item, "interrupted", now)
            self.service._observe(conn, candidate, control["source"], now)
            # Keep the observation revision and invalidate proposals made before this input.
            observed_world = read_world(conn)
            observed_world["sandbox"] = state
            if kind != "grab_cancel":
                observed_world["conversation"] = None
                if observed_world.get("initiative"):
                    observed_world["initiative"]["active_turn"] = None
            result = {
                "request_id": rid,
                "status": "applied",
                "command_revision": command_revision(observed_world) + 1,
                "observation": candidate,
            }
            if kind == "grab_begin":
                result["grab_id"] = rid
            if kind == "spawn":
                result["object_id"] = oid
            self._event(
                conn,
                observed_world,
                "external_intervention",
                {
                    "actor": "user",
                    "action": action,
                    "request_id": rid,
                },
                now,
                request_id=rid,
                envelope=envelope,
                result=result,
            )
            self._save(conn, observed_world)
            return {**result, "replayed": False}

    @staticmethod
    def _object(observation, oid):
        if not isinstance(oid, str) or oid not in observation["objects"]:
            raise ActionError("Object does not exist.")
        obj = observation["objects"][oid]
        if "spatial" not in obj or obj["spatial"]["attachment"] is not None:
            raise ActionError("Place the held object before moving it externally.")
        return obj

    def suspend(self, observation, stop, suspended):
        with self.service._transaction() as (conn, now):
            control = self._owned(conn, now)
            world = read_world(conn)
            state = world["sandbox"]
            if state["suspended"] == suspended:
                return
            if suspended:
                stop()
                for item in self.service._active(conn):
                    item["status"] = "interrupted"
                    item["error"] = {"code": "sandbox_paused", "message": "Sandbox paused."}
                    self.service._record(conn, item, "interrupted", now)
                if observation["pose"] is not None:
                    self.service._observe(conn, observation, control["source"], now)
                    world = read_world(conn)
                    world["sandbox"] = state
                state["grab"] = None
            state["suspended"] = suspended
            self._save(conn, world)

    def physics(self, observation, dt, *, simulate=True):
        """Persist bounded physics; collision events fire once per category per flight."""
        with self.service._transaction() as (conn, now):
            control = self._owned(conn, now)
            world = read_world(conn)
            state = world["sandbox"]
            before = encode(state)
            candidate = copy.deepcopy(observation)
            grab = state["grab"]
            if grab and now >= grab["expires_at"]:
                state["grab"] = None
                self._event(conn, world, "grab_released", {"reason": "pointer_timeout"}, now)
            simulate = simulate and not state["suspended"] and not self.service._active(conn)
            if simulate and state["grab"] is None:
                # Also observe balls created/placed by Ariane: free objects obey
                # the same floor regardless of who put them there.
                for oid, obj in candidate["objects"].items():
                    if (
                        obj["asset"] == "ball"
                        and obj["spatial"]["attachment"] is None
                        and obj["spatial"]["position"][1] > 0.060001
                    ):
                        state["flights"].setdefault(
                            oid, {"velocity": [0, 0, 0], "contacts": [], "source": "simulation"}
                        )
                for oid, flight in list(state["flights"].items()):
                    obj = self._object(candidate, oid)
                    obstacles = [
                        {
                            "position": other["spatial"]["position"],
                            "radius": 0.06 if other["asset"] == "ball" else 0.14,
                        }
                        for other_id, other in candidate["objects"].items()
                        if other_id != oid
                    ]
                    outcome = step_ball(
                        obj["spatial"]["position"],
                        flight["velocity"],
                        min(dt, 0.25),
                        avatar_position2=candidate["avatar"]["position"],
                        obstacles=obstacles,
                    )
                    object_position(obj, outcome["position"])
                    flight["velocity"] = outcome["velocity"]
                    fresh = sorted(set(outcome["contacts"]) - set(flight["contacts"]))
                    flight["contacts"] = sorted(set(flight["contacts"]) | set(outcome["contacts"]))
                    if fresh:
                        self._event(
                            conn,
                            world,
                            "object_contact",
                            {
                                "actor": "simulation",
                                "object_id": oid,
                                "contacts": fresh,
                                "position": outcome["position"],
                                "collision_model": "static-proxies",
                            },
                            now,
                        )
                    if outcome["sleeping"]:
                        del state["flights"][oid]
                        self._event(
                            conn,
                            world,
                            "object_rest",
                            {
                                "actor": "simulation",
                                "object_id": oid,
                                "position": outcome["position"],
                            },
                            now,
                        )
            if candidate != observation:
                if self.service._active(conn):
                    raise ActionError("Cannot advance physics while a body action is active.")
                self.service._observe(conn, candidate, control["source"], now)
                updated = read_world(conn)
                updated["sandbox"] = state
                world = updated
            if before != encode(state) or candidate != observation:
                self._save(conn, world)
            return candidate, copy.deepcopy(state)
