"""Durable body executions with a fenced controller lease and observed outcomes.

This module does not animate a body. Controller handles belong to trusted drivers;
agent tools expose only get_world, submit, get, cancel and supported_actions.
"""

import copy
import json
import math
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from promethee.migrations import read_world
from promethee.runtime import encode
from promethee.world import (
    BODY_ACTION_FIELDS,
    ActionError,
    identifier,
    validate_body_action,
    validate_observation,
)

ACTIVE = {"accepted", "running"}
TERMINAL = {"rejected", "completed", "failed", "cancelled", "interrupted"}


def timestamp(now):
    return datetime.fromtimestamp(now, UTC).isoformat()


def positive_seconds(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError("Timeouts must be positive finite seconds.")
    return float(value)


class ExecutionService:
    def __init__(self, runtime, *, clock=time.time, cancel_timeout=2.0):
        self.runtime = runtime
        self.clock = clock
        self.cancel_timeout = positive_seconds(cancel_timeout)

    @staticmethod
    def _control(conn):
        return json.loads(conn.execute("SELECT data FROM controller WHERE id=1").fetchone()[0])

    @staticmethod
    def _save_control(conn, control):
        conn.execute("UPDATE controller SET data=? WHERE id=1", (encode(control),))

    @staticmethod
    def _get(conn, request_id):
        row = conn.execute(
            "SELECT data FROM executions WHERE request_id=?", (request_id,)
        ).fetchone()
        if row is None:
            raise ActionError("Unknown execution.")
        return json.loads(row[0])

    @staticmethod
    def _active(conn):
        return [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT data FROM executions WHERE status IN ('accepted','running')"
            )
        ]

    @staticmethod
    def _record(conn, item, kind, now):
        item["updated_at"] = timestamp(now)
        conn.execute(
            "INSERT INTO executions VALUES (?,?,?) ON CONFLICT(request_id) DO UPDATE "
            "SET status=excluded.status,data=excluded.data",
            (item["request_id"], item["status"], encode(item)),
        )
        event = {"kind": kind, "recorded_at": timestamp(now), "execution": copy.deepcopy(item)}
        conn.execute(
            "INSERT INTO execution_events(request_id,data) VALUES (?,?)",
            (item["request_id"], encode(event)),
        )

    @staticmethod
    def _unconfirm(conn):
        world = read_world(conn)
        if world["body"]["status"] != "unconfirmed":
            world["body"]["status"] = "unconfirmed"
            world["revision"] += 1
            conn.execute("UPDATE world SET data=? WHERE id=1", (encode(world),))

    @staticmethod
    def _observe(conn, observation, source, now):
        observed = validate_observation(observation)
        if source != "logical-test" and observed["pose"] is None:
            raise ActionError("A real body observation requires an articulated pose.")
        world = read_world(conn)
        before = copy.deepcopy(world)
        if world.get("appearance") is not None and observed.get("appearance") is None:
            raise ActionError("A prepared appearance requires its matching observed checkpoint.")
        world.update(observed)
        world["body"] = {"status": "confirmed", "observed_at": timestamp(now), "source": source}
        if world != before:
            world["revision"] += 1
            conn.execute("UPDATE world SET data=? WHERE id=1", (encode(world),))

    def _interrupt(self, conn, items, code, now):
        for item in items:
            item["status"] = "interrupted"
            item["error"] = {"code": code, "message": "Final body state requires reconciliation."}
            self._record(conn, item, "interrupted", now)
        self._unconfirm(conn)

    def _expire(self, conn, now):
        control = self._control(conn)
        if control["session_id"] and now >= control["expires_at"]:
            self._interrupt(conn, self._active(conn), "controller_lost", now)
            self._save_control(conn, {"session_id": None})
            return
        expired = [
            item
            for item in self._active(conn)
            if item["cancel_requested"] and now >= item["cancel_deadline"]
        ]
        if expired:
            self._interrupt(conn, expired, "cancel_timeout", now)

    @contextmanager
    def _transaction(self):
        with self.runtime.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            now = self.clock()
            self._expire(conn, now)
            # Expiry remains durable even if the following request is malformed or stale.
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            yield conn, self.clock()

    def get_world(self):
        """Read the latest persisted observation after expiring a missing controller."""
        with self._transaction() as (conn, _):
            return read_world(conn)

    def get(self, request_id):
        identifier(request_id)
        with self._transaction() as (conn, _):
            return self._get(conn, request_id)

    def events(self, *, after=0, limit=100):
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Use a non-negative cursor and a limit between 1 and 1000.")
        with self._transaction() as (conn, _):
            return [
                {"seq": seq, **json.loads(data)}
                for seq, data in conn.execute(
                    "SELECT seq,data FROM execution_events WHERE seq>? ORDER BY seq LIMIT ?",
                    (after, limit),
                )
            ]

    def supported_actions(self):
        with self._transaction() as (conn, _):
            control = self._control(conn)
            return control.get("supported_actions", []) if control["session_id"] else []

    def begin_turn(self, *, timeout=60):
        """Trusted conversation host only; never expose this as a model tool.

        A correction or host restart opens a new turn. It invalidates previous
        proposals without cancelling an already accepted body action.
        """
        self.runtime.require_session()
        timeout = positive_seconds(timeout)
        turn_id = "turn-" + uuid4().hex
        with self._transaction() as (conn, now):
            world = read_world(conn)
            world["conversation"] = {"turn_id": turn_id, "expires_at": now + timeout}
            world["revision"] += 1
            conn.execute("UPDATE world SET data=? WHERE id=1", (encode(world),))
        return turn_id

    @staticmethod
    def _check_turn(conn, turn_id, now):
        current = read_world(conn)["conversation"]
        if current is None or current["turn_id"] != turn_id or now >= current["expires_at"]:
            raise ActionError("Conversation turn is obsolete or expired.")

    def end_turn(self, turn_id):
        """Atomically claim a current reply for delivery, or invalidate a failed call."""
        with self._transaction() as (conn, now):
            self._check_turn(conn, turn_id, now)
            world = read_world(conn)
            world["conversation"] = None
            world["revision"] += 1
            conn.execute("UPDATE world SET data=? WHERE id=1", (encode(world),))

    def submit(self, request_id, expected_revision, action, *, turn_id=None):
        identifier(request_id)
        if request_id.startswith("activity-"):
            raise ActionError("The activity- request namespace is reserved.")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ActionError("expected_revision must be a non-negative integer.")
        envelope = {
            "request_id": request_id,
            "expected_revision": expected_revision,
            "action": action,
        }
        if turn_id is not None:
            identifier(turn_id)
            envelope["turn_id"] = turn_id
        payload = encode(envelope)
        with self._transaction() as (conn, now):
            row = conn.execute(
                "SELECT data FROM executions WHERE request_id=?", (request_id,)
            ).fetchone()
            if row:
                previous = json.loads(row[0])
                if encode(previous["envelope"]) != payload:
                    raise ActionError("Request ID reused with a different envelope.")
                return {**previous, "replayed": True}
            if turn_id is not None:
                self._check_turn(conn, turn_id, now)
            if conn.execute("SELECT 1 FROM commands WHERE request_id=?", (request_id,)).fetchone():
                raise ActionError("Request ID already belongs to a logical command.")
            world, control = read_world(conn), self._control(conn)
            code, message = None, None
            if world["data_origin"] == "legacy":
                code, message = "legacy_world", "Create a new world for body execution."
            elif expected_revision != world["revision"]:
                code, message = "revision_conflict", "Read the world again before planning."
            elif not control["session_id"] or world["body"]["status"] != "confirmed":
                code, message = (
                    "controller_unavailable",
                    "A controller must reconcile the body first.",
                )
            elif self._active(conn):
                code, message = "busy", "Another body execution is active."
            else:
                try:
                    validate_body_action(world, action)
                    if action["kind"] not in control["supported_actions"]:
                        raise ActionError("The controller does not implement this action.")
                except ActionError as exc:
                    code, message = "invalid_action", str(exc)
            item = {
                "request_id": request_id,
                "envelope": json.loads(payload),
                "status": "rejected" if code else "accepted",
                "source": control.get("source"),
                "controller_session": control["session_id"],
                "dispatched": False,
                "last_feedback_seq": -1,
                "cancel_requested": False,
                "cancel_sent": False,
                "created_at": timestamp(now),
            }
            if code:
                item["error"] = {"code": code, "message": message}
            self._record(conn, item, item["status"], now)
            return {**item, "replayed": False}

    def cancel(self, request_id, *, turn_id=None):
        identifier(request_id)
        with self._transaction() as (conn, now):
            item = self._get(conn, request_id)
            if item["status"] in TERMINAL or item["cancel_requested"]:
                return item
            if turn_id is not None:
                self._check_turn(conn, turn_id, now)
            item["cancel_requested"] = True
            if not item["dispatched"]:
                item["status"] = "cancelled"
                self._record(conn, item, "cancelled", now)
            else:
                item["cancel_deadline"] = now + self.cancel_timeout
                self._record(conn, item, "cancel_requested", now)
            return item

    def acquire_controller(self, *, source, supported_actions, lease_seconds=5.0):
        """Trusted driver entry point, never an agent tool."""
        if source not in {"logical-test", "kinematic", "physics"}:
            raise ValueError("Unknown controller provenance.")
        if not isinstance(supported_actions, (list, tuple, set)) or not supported_actions:
            raise ValueError("Declare at least one supported action.")
        if any(
            not isinstance(kind, str) or kind not in BODY_ACTION_FIELDS
            for kind in supported_actions
        ):
            raise ValueError("Unknown supported action.")
        lease_seconds = positive_seconds(lease_seconds)
        with self._transaction() as (conn, now):
            world = read_world(conn)
            expected_origin = "fixture" if source == "logical-test" else "session"
            if world["data_origin"] != expected_origin:
                raise ActionError(f"A {source} controller requires a {expected_origin} world.")
            if self._control(conn)["session_id"]:
                raise ActionError("A controller already owns this world.")
            session_id = "controller-" + uuid4().hex
            self._save_control(
                conn,
                {
                    "session_id": session_id,
                    "source": source,
                    "supported_actions": sorted(set(supported_actions)),
                    "lease_seconds": lease_seconds,
                    "expires_at": now + lease_seconds,
                },
            )
            self._unconfirm(conn)
        return ControllerHandle(self, session_id)

    def _owned(self, conn, session_id, now):
        control = self._control(conn)
        if control["session_id"] != session_id or now >= control.get("expires_at", 0):
            return None
        return control

    def _heartbeat(self, session_id):
        with self._transaction() as (conn, now):
            control = self._owned(conn, session_id, now)
            if control is None:
                return False
            control["expires_at"] = now + control["lease_seconds"]
            self._save_control(conn, control)
            return True

    def _reconcile(self, session_id, observation, *, stopped):
        if stopped is not True:
            raise ActionError("Reconciliation requires the controller to attest it is stopped.")
        observed = validate_observation(observation)
        with self._transaction() as (conn, now):
            control = self._owned(conn, session_id, now)
            if control is None:
                return False
            if self._active(conn):
                raise ActionError("Cannot reconcile while an execution is active.")
            self._observe(conn, observed, control["source"], now)
            return True

    def _claim(self, session_id, *, cancellation=False):
        with self._transaction() as (conn, now):
            if self._owned(conn, session_id, now) is None:
                return None
            for item in self._active(conn):
                if item["controller_session"] != session_id:
                    continue
                if cancellation:
                    if item["cancel_requested"] and not item["cancel_sent"]:
                        item["cancel_sent"] = True
                        self._record(conn, item, "cancel_dispatched", now)
                        return item
                elif not item["dispatched"] and not item["cancel_requested"]:
                    if read_world(conn)["body"]["status"] != "confirmed":
                        return None
                    item["dispatched"] = True
                    self._record(conn, item, "dispatched", now)
                    return item
            return None

    def _feedback(self, session_id, request_id, sequence, status, *, observation=None, error=None):
        identifier(request_id)
        if type(sequence) is not int or sequence < 0:
            raise ActionError("Feedback sequence must be a non-negative integer.")
        if status not in {"running", "completed", "failed", "cancelled"}:
            raise ActionError("Invalid controller status.")
        with self._transaction() as (conn, now):
            control = self._owned(conn, session_id, now)
            if control is None:
                return False
            item = self._get(conn, request_id)
            if item["controller_session"] != session_id or item["status"] in TERMINAL:
                return False
            if sequence <= item["last_feedback_seq"]:
                return False
            if not item["dispatched"]:
                raise ActionError("Feedback cannot precede dispatch.")
            if status == "completed" and item["status"] != "running":
                raise ActionError("Completion must follow a running acknowledgement.")
            if status == "cancelled" and not item["cancel_requested"]:
                raise ActionError("No cancellation was requested.")
            if status in {"completed", "cancelled"} and observation is None:
                raise ActionError("A terminal result requires a full observed state.")
            if status == "failed" and (not isinstance(error, str) or not error.strip()):
                raise ActionError("Failure requires a cause.")
            if observation is not None:
                self._observe(conn, observation, control["source"], now)
                item["observation"] = copy.deepcopy(observation)
                item["observed_at"] = timestamp(now)
            elif status == "failed":
                self._unconfirm(conn)
            item["status"] = status
            item["last_feedback_seq"] = sequence
            if status == "failed":
                item["error"] = {"code": "controller_failure", "message": error}
            self._record(conn, item, status, now)
            return True

    def _release(self, session_id):
        with self._transaction() as (conn, now):
            if self._owned(conn, session_id, now) is None:
                return False
            self._interrupt(conn, self._active(conn), "controller_released", now)
            self._save_control(conn, {"session_id": None})
            return True


class ControllerHandle:
    """Fenced driver operations; do not expose this handle to model tools."""

    def __init__(self, service, session_id):
        self._service = service
        self.session_id = session_id

    def heartbeat(self):
        return self._service._heartbeat(self.session_id)

    def reconcile(self, observation, *, stopped):
        return self._service._reconcile(self.session_id, observation, stopped=stopped)

    def claim_next(self):
        return self._service._claim(self.session_id)

    def claim_cancellation(self):
        return self._service._claim(self.session_id, cancellation=True)

    def feedback(self, request_id, sequence, status, *, observation=None, error=None):
        return self._service._feedback(
            self.session_id, request_id, sequence, status, observation=observation, error=error
        )

    def release(self):
        return self._service._release(self.session_id)
