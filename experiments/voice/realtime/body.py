"""Local qualification adapter; no GPU/process starts until BodyAdapter.start().

Create on the server thread, open TextHost on ``adapter.data_dir``, then start
after GPU coordination. ``poll()['motion']`` is an observed one-frame stream,
not a clip: normalized VRM WORLD quaternions, root WORLD position, 20 Hz.
The frontend may interpolate received observations but must not extrapolate.
All controller/preparation ownership stays on one dedicated thread. MCP may
submit to the same ExecutionService database; there is only one body writer.
"""

import copy
import hashlib
import json
import queue
import threading
import time
import traceback
from concurrent.futures import Future
from pathlib import Path
from uuid import uuid4

from presence import PresenceController

from promethee.appearance_process import AppearancePreparation
from promethee.avatar_live import AvatarLiveServer
from promethee.avatar_reach import PIXIV_SHA256, load_profile
from promethee.execution import ExecutionService
from promethee.motion_process import start_ardy_process
from promethee.runtime import Runtime

ROOT = Path(__file__).resolve().parents[3]


class _Snapshots(AvatarLiveServer):
    """Reuse the existing coherent publisher, without starting its HTTP server."""

    def __init__(self, service):
        self.service = service
        self.clock = time.monotonic
        self.latest = self.bootstrap = self.published_at = None
        self.last_request = None
        self.sequence = 0


class BodyAdapter:
    def __init__(
        self,
        data_dir,
        *,
        avatar,
        ardy_python,
        checkpoint_root,
        wsl=None,
        encoder_url="http://127.0.0.1:9551",
        seed=138124,
        node="node",
    ):
        self.data_dir = Path(data_dir).resolve()
        self.avatar = Path(avatar).resolve()
        if hashlib.sha256(self.avatar.read_bytes()).hexdigest() != PIXIV_SHA256:
            raise ValueError("Use the pinned pixiv VRM appearance.")
        database = self.data_dir / "world.sqlite3"
        if database.exists():
            raise ValueError(
                "Use a new qualification directory; existing worlds are not overwritten."
            )
        self.service = ExecutionService(
            Runtime(database, data_origin="session", session_kind="qualification")
        )
        self.options = {
            "python": ardy_python,
            "checkpoint_root": checkpoint_root,
            "output": self.data_dir / "motions",
            "wsl": wsl,
            "encoder_url": encoder_url,
        }
        self.seed, self.node = seed, node
        self._commands = queue.Queue(maxsize=16)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        self._closed = False
        self._snapshot = {
            "ready": False,
            "closed": False,
            "state": None,
            "motion": None,
            "bootstrap": None,
            "world": self.service.get_world(),
            "message": "Corps non démarré.",
            "error": None,
        }
        (self.data_dir / "body-purpose.json").write_text(
            json.dumps(
                {
                    "purpose": "real-time voice/body qualification; excluded from personal memory",
                    "continuous_motion": True,
                    "prepared_appearance": True,
                    "seed": seed,
                    "backend": {key: str(value) for key, value in self.options.items()},
                    "avatar_sha256": PIXIV_SHA256,
                    "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "no_archived_motion_replay": True,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def start(self):
        """Nonblocking. Caller must arrange the text encoder and GPU budget first."""
        with self._lock:
            if self._closed or self._thread is not None:
                raise RuntimeError("Body can only be started once.")
            self._snapshot["message"] = "Chargement du corps ARDY réel."
            self._thread = threading.Thread(target=self._run, name="realtime-body", daemon=True)
            self._thread.start()
        return self

    def request(self, action, *, request_id=None, expected_revision=None, turn_id=None):
        """Submit ordinary move/posture actions; accepted never means completed.

        A supplied request_id is preserved for retries. Calls from an agent
        should pass its turn_id (MCP already does this through the shared DB).
        """
        return self._command(
            "request",
            action=copy.deepcopy(action),
            request_id=request_id or "realtime-" + uuid4().hex,
            expected_revision=expected_revision,
            turn_id=turn_id,
        )

    def cancel(self, request_id=None, *, turn_id=None):
        """Cancel a named execution or all accepted/running actions; idle returns None."""
        return self._command("cancel", request_id=request_id, turn_id=turn_id)

    def set_presence(self, enabled):
        """Enable generated conversational gestures for this temporary trial."""
        if type(enabled) is not bool:
            raise ValueError("Presence must be a boolean.")
        return self._command("presence", enabled=enabled)

    def _command(self, kind, **value):
        future = Future()
        with self._lock:
            if self._closed or self._thread is None or not self._thread.is_alive():
                raise RuntimeError("Body loop is not running.")
            self._commands.put_nowait((future, kind, value))
        try:
            return future.result(timeout=15)
        except TimeoutError:
            # A still-queued request must not execute after this timeout.
            future.cancel()
            raise

    def poll(self):
        """Read a detached snapshot. Safe from the HTTP thread; never ticks ARDY."""
        with self._lock:
            result = copy.deepcopy(self._snapshot)
        stamp = result.get("sampled_at_monotonic")
        result["age_seconds"] = None if stamp is None else max(0, time.monotonic() - stamp)
        result["stale"] = stamp is None or result["age_seconds"] > 1 or result["closed"]
        return result

    def _drain(self, controller, publisher):
        # Bound work per tick so repeated HTTP submissions cannot starve playback.
        for _ in range(16):
            try:
                future, kind, value = self._commands.get_nowait()
            except queue.Empty:
                break
            if not future.set_running_or_notify_cancel():
                continue
            try:
                if kind == "presence":
                    controller.set_presence(value["enabled"])
                    item = {"enabled": value["enabled"]}
                elif kind == "request":
                    if not controller.ready:
                        raise RuntimeError("Body is still initializing.")
                    if value["expected_revision"] is None:
                        value["expected_revision"] = self.service.get_world()["revision"]
                    item = self.service.submit(**value)
                    publisher.last_request = item["request_id"]
                else:
                    if value["request_id"] is None:
                        controller.set_presence(False)
                    if value["request_id"] is None:
                        # MCP may have accepted a command before this loop claimed it.
                        # Read durable executions, not just controller.active.
                        with self.service.runtime.connection() as conn:
                            ids = [
                                row[0]
                                for row in conn.execute(
                                    "SELECT request_id FROM executions "
                                    "WHERE status IN ('accepted', 'running') ORDER BY rowid"
                                )
                            ]
                        item = None
                        for request_id in ids:
                            item = self.service.cancel(request_id, turn_id=value["turn_id"])
                    else:
                        item = self.service.cancel(**value)
                    if item is not None:
                        publisher.last_request = item["request_id"]
                future.set_result(item)
            except Exception as exc:
                future.set_exception(exc)

    def _publish(self, controller, publisher):
        publisher.update(controller)
        state = json.loads(publisher.latest) if publisher.latest else None
        motion = None
        if controller.ready and state:
            appearance = state["observation"].get("appearance")
            if appearance is None:
                raise RuntimeError("Refusing an unprepared visible pose.")
            prepared = appearance["frame"]
            names = list(prepared["rotations"])
            root = list(state["observation"]["pose"]["positions"][0])
            root[1] += prepared["root_y_offset"]
            motion = {
                "id": controller.handle.session_id,
                "sequence": state["sequence"],
                "fps": 20,
                "scale": load_profile()["scale"],
                "bone_names": names,
                "rotation_space": "normalized-bone-world",
                "root_space": "world",
                "streaming": True,
                "sampled_at_unix_ms": time.time() * 1000,
                "frames": [
                    {"root_position": root, "rotations": [prepared["rotations"][n] for n in names]}
                ],
            }
        result = {
            "ready": controller.ready,
            "closed": False,
            "state": state,
            "motion": motion,
            "bootstrap": json.loads(publisher.bootstrap) if publisher.bootstrap else None,
            "world": self.service.get_world(),
            "message": controller.message,
            "presence": {
                "enabled": controller.presence_enabled,
                "status": controller.presence_status,
                "error": controller.presence_error,
            },
            "error": None,
            "sampled_at_monotonic": time.monotonic(),
        }
        with self._lock:
            self._snapshot = result

    def _run(self):
        worker = preparation = controller = None
        try:
            worker = start_ardy_process(**self.options)
            preparation = AppearancePreparation(
                avatar=self.avatar,
                script=ROOT / "web/avatar/measure-feet.mjs",
                output=self.data_dir / "appearance",
                node=self.node,
            )
            controller = PresenceController(
                self.service,
                worker,
                seed=self.seed,
                appearance_preparation=preparation,
                continuous_motion=True,
            )
            publisher = _Snapshots(self.service)
            while not self._stop.is_set():
                started = time.monotonic()
                self._drain(controller, publisher)
                controller.tick()
                self._publish(controller, publisher)
                self._stop.wait(max(0.001, 0.05 - (time.monotonic() - started)))
        except Exception as exc:
            (self.data_dir / "body-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            with self._lock:
                self._snapshot.update(ready=False, error=str(exc), message="Corps indisponible.")
        finally:
            try:
                if controller is not None:
                    controller.close()
                else:
                    if worker is not None:
                        worker.close()
                    if preparation is not None:
                        preparation.close()
            finally:
                with self._lock:
                    self._closed = True
                    self._snapshot.update(ready=False, closed=True)
                while True:
                    try:
                        future, _, _ = self._commands.get_nowait()
                    except queue.Empty:
                        break
                    if future.set_running_or_notify_cancel():
                        future.set_exception(RuntimeError("Body loop closed before command."))

    def close(self):
        """Release only this adapter's controller and its owned child processes."""
        self._stop.set()
        with self._lock:
            thread = self._thread
            if thread is None:
                self._closed = True
                self._snapshot.update(ready=False, closed=True)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=20)
            if thread.is_alive():
                raise TimeoutError("Body shutdown has not completed; owned loop still running.")
