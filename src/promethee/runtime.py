"""SQLite snapshots, idempotent commands, and resumable scripted activities."""

import copy
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from promethee.catalog import INITIAL_WORLD
from promethee.migrations import (
    check_version,
    create_conversation_tables,
    create_execution_tables,
    read_world,
)
from promethee.world import ActionError, apply, identifier


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


class Runtime:
    def __init__(self, path, *, data_origin=None, create=True):
        if data_origin not in (None, "fixture", "session"):
            raise ValueError("New worlds must have fixture or session origin.")
        self.path = Path(path)
        self.create = create
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='world'"
            ).fetchone()
            if exists:
                state = read_world(conn)
                check_version(state)
                if data_origin is not None and state["data_origin"] != data_origin:
                    raise ValueError("Existing world's data origin cannot be changed.")
                return
            if not create:
                raise ValueError("The database does not contain a Promethee world.")
            conn.execute("CREATE TABLE world (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT)")
            conn.execute("""CREATE TABLE commands (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL UNIQUE,
                    action TEXT NOT NULL,
                    result TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )""")
            conn.execute("CREATE TABLE activities (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            create_execution_tables(conn)
            create_conversation_tables(conn)
            conn.execute(
                "INSERT INTO world VALUES (1, ?)",
                (
                    encode(
                        {
                            **INITIAL_WORLD,
                            "data_origin": data_origin or "fixture",
                            "world_id": uuid4().hex,
                        }
                    ),
                ),
            )

    @contextmanager
    def connection(self):
        target = self.path if self.create else self.path.resolve().as_uri() + "?mode=rw"
        conn = sqlite3.connect(target, timeout=10, uri=not self.create)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def snapshot(self):
        with self.connection() as conn:
            return read_world(conn)

    def require_session(self):
        state = self.snapshot()
        if state["data_origin"] != "session":
            raise ActionError(
                "Agent access requires a new session world, not fixture or legacy data."
            )
        return state

    @staticmethod
    def _require_logical(conn):
        if read_world(conn)["data_origin"] == "session":
            raise ActionError(
                "Session worlds require the body controller; logical actions are disabled."
            )
        if conn.execute(
            "SELECT 1 FROM executions WHERE status IN ('accepted','running')"
        ).fetchone():
            raise ActionError("busy: a body execution is active.")
        if json.loads(conn.execute("SELECT data FROM controller WHERE id=1").fetchone()[0])[
            "session_id"
        ]:
            raise ActionError("Controller-owned worlds cannot be changed through logical actions.")

    def events(self):
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT seq, request_id, action, result, created_at FROM commands ORDER BY seq"
            ).fetchall()
        return [
            {
                "seq": seq,
                "request_id": rid,
                "action": json.loads(action),
                "result": json.loads(result),
                "created_at": date,
            }
            for seq, rid, action, result, date in rows
        ]

    def _execute(self, conn, request_id, action):
        self._require_logical(conn)
        identifier(request_id)
        if conn.execute("SELECT 1 FROM executions WHERE request_id=?", (request_id,)).fetchone():
            raise ActionError("Request ID already belongs to a body execution.")
        payload = encode(action)
        previous = conn.execute(
            "SELECT action, result FROM commands WHERE request_id=?", (request_id,)
        ).fetchone()
        if previous:
            if previous[0] != payload:
                raise ActionError("Request ID reused with a different action.")
            return {**json.loads(previous[1]), "replayed": True}
        state = read_world(conn)
        before = copy.deepcopy(state)
        try:
            apply(state, action)
        except ActionError as exc:
            result = {"ok": False, "error": str(exc)}
        else:
            if state != before:
                state["revision"] += 1
                conn.execute("UPDATE world SET data=? WHERE id=1", (encode(state),))
            result = {"ok": True}
        conn.execute(
            "INSERT INTO commands(request_id, action, result, created_at) VALUES (?, ?, ?, ?)",
            (request_id, payload, encode(result), datetime.now(UTC).isoformat()),
        )
        return {**result, "replayed": False}

    def execute(self, request_id, action):
        identifier(request_id)
        if request_id.startswith("activity-"):
            raise ActionError("The activity- request namespace is reserved.")
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            return self._execute(conn, request_id, action)

    def start_activity(self, activity_id, steps):
        identifier(activity_id)
        if len(activity_id) > 40 or not isinstance(steps, list) or not 1 <= len(steps) <= 100:
            raise ActionError("Use an activity ID up to 40 characters and 1-100 steps.")
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._require_logical(conn)
            row = conn.execute("SELECT data FROM activities WHERE id=?", (activity_id,)).fetchone()
            if row:
                saved = json.loads(row[0])
                if saved["steps"] != steps:
                    raise ActionError("Activity ID reused with a different plan.")
                return saved
            # Validate the complete script against a disposable snapshot before persisting it.
            preview = json.loads(conn.execute("SELECT data FROM world WHERE id=1").fetchone()[0])
            for step in steps:
                apply(preview, step)
            activity = {
                "id": activity_id,
                "steps": copy.deepcopy(steps),
                "cursor": 0,
                "status": "running",
            }
            conn.execute("INSERT INTO activities VALUES (?, ?)", (activity_id, encode(activity)))
            return activity

    def activity(self, activity_id):
        with self.connection() as conn:
            return self._activity(conn, activity_id)

    @staticmethod
    def _activity(conn, activity_id):
        row = conn.execute("SELECT data FROM activities WHERE id=?", (activity_id,)).fetchone()
        if not row:
            raise ActionError("Unknown activity.")
        return json.loads(row[0])

    @staticmethod
    def _save_activity(conn, activity):
        conn.execute("UPDATE activities SET data=? WHERE id=?", (encode(activity), activity["id"]))

    def set_paused(self, activity_id, paused):
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            activity = self._activity(conn, activity_id)
            if activity["status"] not in ("running", "paused"):
                raise ActionError("Only running or paused activities can change pause state.")
            activity["status"] = "paused" if paused else "running"
            self._save_activity(conn, activity)
            return activity

    def advance(self, activity_id):
        """Commit one action and its plan cursor in the same transaction."""
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            activity = self._activity(conn, activity_id)
            if activity["status"] != "running":
                return activity
            cursor = activity["cursor"]
            # Namespaced IDs reserve this command for this activity step.
            result = self._execute(
                conn, f"activity-{activity_id}-{cursor}", activity["steps"][cursor]
            )
            if result["ok"]:
                activity["cursor"] += 1
                if activity["cursor"] == len(activity["steps"]):
                    activity["status"] = "completed"
            else:
                activity["status"] = "failed"
                activity["error"] = result["error"]
            self._save_activity(conn, activity)
            return activity
