"""Trusted host storage for native Hermes history, atomically fenced by world turn.

This is not a reasoning loop or a memory summarizer. Failed/superseded native
results never become context. User messages survive them; observed body state
still comes from the runtime. No method here is exposed as an agent tool.
"""

import json
from uuid import uuid4

from promethee.execution import positive_seconds, timestamp
from promethee.migrations import read_world
from promethee.runtime import encode
from promethee.world import ActionError

HISTORY_BYTES = 524_288


def bounded_history(messages):
    if not isinstance(messages, list) or any(
        not isinstance(message, dict) or message.get("role") not in {"user", "assistant", "tool"}
        for message in messages
    ):
        raise ValueError("Expected native user, assistant and tool messages.")
    if len(encode(messages).encode("utf-8")) > HISTORY_BYTES:
        raise ValueError("Conversation context limit reached; no history was silently truncated.")
    return messages


class ConversationStore:
    def __init__(self, service):
        service.runtime.require_session()
        self.service = service

    def recover(self):
        """A replacement exclusive host discards pending calls without resubmission."""
        with self.service._transaction() as (conn, _):
            for turn_id, data in conn.execute(
                "SELECT turn_id,data FROM conversation_turns"
            ).fetchall():
                record = json.loads(data)
                delivery = record.get("speech_delivery")
                if delivery and delivery["status"] in {"preparing", "playing"}:
                    delivery.update(
                        status="interrupted",
                        reason="host_restarted",
                        updated_at=timestamp(self.service.clock()),
                    )
                    conn.execute(
                        "UPDATE conversation_turns SET data=? WHERE turn_id=?",
                        (encode(record), turn_id),
                    )
            conn.execute(
                "UPDATE conversation_turns SET status='interrupted' WHERE status='running'"
            )
            world = read_world(conn)
            initiative = world.get("initiative")
            if world["conversation"] is not None or (initiative and initiative["active_turn"]):
                world["conversation"] = None
                if initiative:
                    initiative["active_turn"] = None
                world["revision"] += 1
                conn.execute("UPDATE world SET data=? WHERE id=1", (encode(world),))

    @staticmethod
    def _record(conn, turn_id):
        row = conn.execute(
            "SELECT status,data FROM conversation_turns WHERE turn_id=?", (turn_id,)
        ).fetchone()
        if row is None:
            raise ActionError("Unknown conversation turn.")
        return row[0], json.loads(row[1])

    @staticmethod
    def _history(conn):
        # Native Hermes may compact its context. Keep its latest successful
        # result verbatim, then retain subsequent unanswered user corrections.
        row = conn.execute(
            "SELECT seq,data FROM conversation_turns WHERE status='completed' "
            "ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        seq, history = (row[0], json.loads(row[1])["messages"]) if row else (0, [])
        for (data,) in conn.execute(
            "SELECT data FROM conversation_turns WHERE seq>? ORDER BY seq", (seq,)
        ):
            history.append({"role": "user", "content": json.loads(data)["message"]})
        return bounded_history(history)

    def begin(self, message, *, timeout=60):
        with self.service._transaction() as (conn, now):
            return self._begin(conn, now, message, timeout=timeout)

    def _begin(self, conn, now, message, *, timeout=60, trigger="user"):
        """Open within a trusted host transaction, including any initiative reservation."""
        if not isinstance(message, str) or not message.strip() or len(message) > 16000:
            raise ValueError("Expected a nonempty message of at most 16000 characters.")
        timeout = positive_seconds(timeout)
        turn_id = "turn-" + uuid4().hex
        world = read_world(conn)
        history = self._history(conn)
        bounded_history([*history, {"role": "user", "content": message}])
        record = {
            "world_id": world["world_id"],
            "data_origin": world["data_origin"],
            "turn_id": turn_id,
            "message": message,
            "created_at": timestamp(now),
            "trigger": trigger,
            "speech_delivery": None,
        }
        conn.execute("UPDATE conversation_turns SET status='interrupted' WHERE status='running'")
        conn.execute(
            "INSERT INTO conversation_turns(turn_id,status,data) VALUES (?,?,?)",
            (turn_id, "running", encode(record)),
        )
        world["conversation"] = {"turn_id": turn_id, "expires_at": now + timeout}
        if world.get("initiative"):
            world["initiative"]["active_turn"] = None
        world["revision"] += 1
        conn.execute("UPDATE world SET data=? WHERE id=1", (encode(world),))
        return {"turn_id": turn_id, "session_id": world["world_id"], "history": history}

    def finish(self, turn_id, result):
        """Claim a valid response and persist its native context in one commit.

        The caller must also serialize actual text/audio delivery against new
        input. A successful commit is not evidence that audio was heard.
        """
        if (
            not isinstance(result, dict)
            or result.get("type") != "result"
            or result.get("turn_id") != turn_id
            or result.get("failed") is not False
            or result.get("interrupted") is not False
            or not isinstance(result.get("text"), str)
            or not result["text"].strip()
        ):
            raise ValueError("Only a successful matching native conversation result is accepted.")
        messages = bounded_history(result.get("messages"))
        if not messages or messages[-1].get("role") != "assistant":
            raise ValueError("The native history must end with an assistant response.")
        with self.service._transaction() as (conn, now):
            self.service._check_turn(conn, turn_id, now)
            status, record = self._record(conn, turn_id)
            if status != "running":
                raise ActionError("Conversation result was already handled.")
            user_messages = [message for message in messages if message["role"] == "user"]
            # Hermes 0.20.5 can merge adjacent unanswered user messages with
            # two newlines in the returned native history. Verify that exact
            # known tail, never an arbitrary substring in model-produced text.
            tail = []
            for message in reversed(self._history(conn)):
                if message["role"] != "user":
                    break
                tail.append(message["content"])
            permitted = (record["message"], "\n\n".join(reversed(tail)))
            if not user_messages or user_messages[-1].get("content") not in permitted:
                raise ValueError("The native history does not retain this turn's user message.")
            record.update(messages=messages, text=result["text"], finished_at=timestamp(now))
            conn.execute(
                "UPDATE conversation_turns SET status='completed',data=? WHERE turn_id=?",
                (encode(record), turn_id),
            )
            world = read_world(conn)
            world["conversation"] = None
            if world.get("initiative") and world["initiative"]["active_turn"] == turn_id:
                world["initiative"]["active_turn"] = None
            world["revision"] += 1
            conn.execute("UPDATE world SET data=? WHERE id=1", (encode(world),))
        return result["text"]

    def speech_delivery(self, turn_id, generation, status):
        """Trusted audio host receipt; never asserts which words a listener heard."""
        allowed = {"preparing", "playing", "completed", "interrupted", "failed", "text_only"}
        if (
            status not in allowed
            or not isinstance(generation, str)
            or not 1 <= len(generation) <= 128
        ):
            raise ValueError("Invalid speech delivery receipt.")
        with self.service._transaction() as (conn, now):
            turn_status, record = self._record(conn, turn_id)
            if turn_status != "completed":
                raise ActionError("Only a completed text response has speech delivery.")
            previous = record.get("speech_delivery")
            if previous:
                if previous["generation"] != generation:
                    raise ActionError("Speech generation does not match this response.")
                if previous["status"] == status:
                    return previous
                if previous["status"] not in {"preparing", "playing"}:
                    raise ActionError("Speech delivery is already terminal.")
                transitions = {
                    "preparing": {"playing", "interrupted", "failed"},
                    "playing": {"completed", "interrupted", "failed"},
                }
                if status not in transitions[previous["status"]]:
                    raise ActionError("Invalid speech delivery transition.")
            elif status not in {"preparing", "text_only"}:
                raise ActionError("Speech must be registered before playback.")
            delivery = {
                "generation": generation,
                "status": status,
                "updated_at": timestamp(now),
                "playback_started": status == "playing"
                or bool(previous and previous["playback_started"]),
                "heard_by_user": None,
                "heard_text": None,
                "source": "chained-voice-diagnostic",
            }
            record["speech_delivery"] = delivery
            conn.execute(
                "UPDATE conversation_turns SET data=? WHERE turn_id=?", (encode(record), turn_id)
            )
            return delivery

    def abort(self, turn_id, *, status="failed"):
        """Close only this call; preserve user input and never cancel the body."""
        if status not in {"failed", "interrupted"}:
            raise ValueError("Expected failed or interrupted conversation status.")
        with self.service._transaction() as (conn, now):
            previous, record = self._record(conn, turn_id)
            if previous != "running":
                return False
            record["finished_at"] = timestamp(now)
            conn.execute(
                "UPDATE conversation_turns SET status=?,data=? WHERE turn_id=?",
                (status, encode(record), turn_id),
            )
            world = read_world(conn)
            changed = False
            if world["conversation"] and world["conversation"]["turn_id"] == turn_id:
                world["conversation"] = None
                changed = True
            if world.get("initiative") and world["initiative"]["active_turn"] == turn_id:
                world["initiative"]["active_turn"] = None
                changed = True
            if changed:
                world["revision"] += 1
                conn.execute("UPDATE world SET data=? WHERE id=1", (encode(world),))
        return True
