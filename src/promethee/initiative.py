"""Explicit, persisted call budget for the same conversation agent; no activity quota."""

import copy
import hashlib
import json

from promethee.execution import TERMINAL, positive_seconds
from promethee.migrations import read_world
from promethee.runtime import encode
from promethee.world import ActionError


class Initiative:
    def __init__(self, service):
        service.runtime.require_session()
        self.service = service

    @staticmethod
    def _save(conn, world):
        world["revision"] += 1
        conn.execute("UPDATE world SET data=? WHERE id=1", (encode(world),))

    def _fingerprint(self, conn, world):
        control = self.service._control(conn)
        objects = copy.deepcopy(world["objects"])
        for oid, obj in objects.items():
            moving = oid in world.get("sandbox", {}).get("flights", {})
            held = world["avatar"]["holding"] == oid
            if (moving or held) and "spatial" in obj:
                obj["position"] = None
                obj["spatial"]["position"] = None
                obj["spatial"]["rotation"] = None
                obj["in_flight"] = moving
        relevant = {
            "objects": objects,
            "body": world["body"]["status"],
            "capabilities": control.get("supported_actions", []) if control["session_id"] else [],
        }
        return hashlib.sha256(encode(relevant).encode()).hexdigest()

    @staticmethod
    def _budget(value):
        if type(value) is not int or not 1 <= value <= 1000:
            raise ValueError("Supply an explicit budget of 1-1000 agent calls.")
        return value

    def configure(self, *, budget, interval=None):
        budget = self._budget(budget)
        if interval is not None:
            interval = positive_seconds(interval)
            if interval < 1:
                raise ValueError("Initiative cadence cannot be faster than one second.")
        with self.service._transaction() as (conn, now):
            world = read_world(conn)
            if world["initiative"] is not None:
                raise ActionError(
                    "Initiative already configured; change pause or add budget explicitly."
                )
            world["initiative"] = {
                "remaining": budget,
                "used": 0,
                "paused": False,
                "interval": interval,
                "next_at": now + interval if interval else None,
                "cursor": conn.execute(
                    "SELECT COALESCE(MAX(seq),0) FROM execution_events"
                ).fetchone()[0],
                "fingerprint": self._fingerprint(conn, world),
                "pending": {"terminal_count": 0, "latest": [], "world_changed": False},
                "active_turn": None,
            }
            self._save(conn, world)
            return world["initiative"]

    def update(self, *, paused=None, add_budget=None):
        if paused is not None and type(paused) is not bool:
            raise ValueError("Pause must be a boolean.")
        if add_budget is not None:
            self._budget(add_budget)
        with self.service._transaction() as (conn, now):
            world = read_world(conn)
            state = world["initiative"]
            if state is None:
                raise ActionError("Initiative is not configured.")
            before = encode(state)
            if add_budget is not None:
                if state["remaining"] + add_budget > 1000:
                    raise ValueError("Remaining initiative budget cannot exceed 1000 calls.")
                state["remaining"] += add_budget
            if paused is not None and paused != state["paused"]:
                state["paused"] = paused
                if state["interval"]:
                    state["next_at"] = now + state["interval"]
            if paused and state["active_turn"]:
                turn = state["active_turn"]
                conn.execute(
                    "UPDATE conversation_turns SET status='interrupted' "
                    "WHERE turn_id=? AND status='running'",
                    (turn,),
                )
                if world["conversation"] and world["conversation"]["turn_id"] == turn:
                    world["conversation"] = None
                state["active_turn"] = None
            if before != encode(state):
                self._save(conn, world)
            return state

    def observe(self):
        """Coalesce relevant changes while an agent is busy, paused or out of budget."""
        with self.service._transaction() as (conn, _):
            world = read_world(conn)
            state = world["initiative"]
            if state is None:
                return None
            before = encode(state)
            fingerprint = self._fingerprint(conn, world)
            if fingerprint != state["fingerprint"]:
                state["pending"]["world_changed"] = True
                state["fingerprint"] = fingerprint
            for seq, data in conn.execute(
                "SELECT seq,data FROM execution_events WHERE seq>? ORDER BY seq LIMIT 1000",
                (state["cursor"],),
            ):
                event = json.loads(data)
                state["cursor"] = seq
                if event["kind"] in TERMINAL:
                    pending = state["pending"]
                    pending["terminal_count"] += 1
                    pending["latest"] = [
                        *pending["latest"],
                        {
                            "seq": seq,
                            "request_id": event["execution"]["request_id"],
                            "status": event["kind"],
                        },
                    ][-8:]
                elif event["kind"] in {
                    "external_intervention",
                    "object_contact",
                    "object_rest",
                    "grab_released",
                }:
                    state["pending"]["world_changed"] = True
                    state["pending"]["latest"] = [
                        *state["pending"]["latest"],
                        {
                            "seq": seq,
                            **{
                                key: value
                                for key, value in event.items()
                                if key not in {"envelope", "result"}
                            },
                        },
                    ][-8:]
            if before != encode(state):
                self._save(conn, world)
            return state

    def open_turn(self, conversation, *, timeout=60):
        """Atomically reserve one call and create its native conversation record."""
        if conversation.service.runtime.path.resolve() != self.service.runtime.path.resolve():
            raise ValueError("Initiative and conversation must share the same world.")
        with self.service._transaction() as (conn, now):
            world = read_world(conn)
            state = world["initiative"]
            if state is None or state["paused"] or not state["remaining"] or world["conversation"]:
                return None
            if any(
                world.get("sandbox", {}).get(field) for field in ("grab", "flights", "suspended")
            ):
                return None
            # Do not dispatch on a partially collected event backlog.
            latest = conn.execute("SELECT COALESCE(MAX(seq),0) FROM execution_events").fetchone()[0]
            if latest > state["cursor"]:
                return None
            cadence = state["next_at"] is not None and now >= state["next_at"]
            pending = state["pending"]
            if not cadence and not pending["terminal_count"] and not pending["world_changed"]:
                return None
            message = (
                "Runtime initiative wake, not a user message. "
                "Read the current world before deciding. Doing nothing is allowed; "
                "no activity quota or predefined project exists. Changes: "
                + encode({**pending, "cadence_due": cadence, "through_event": state["cursor"]})
            )
            state["remaining"] -= 1
            state["used"] += 1
            state["pending"] = {"terminal_count": 0, "latest": [], "world_changed": False}
            state["next_at"] = now + state["interval"] if state["interval"] else None
            self._save(conn, world)
            opened = conversation._begin(conn, now, message, timeout=timeout, trigger="initiative")
            world = read_world(conn)
            world["initiative"]["active_turn"] = opened["turn_id"]
            self._save(conn, world)
            return {**opened, "message": message}
