"""Exclusive native Hermes host; initiative requires an explicitly configured budget."""

import contextlib
import json
import math
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from promethee.conversation import ConversationStore, ReservationExpired
from promethee.execution import ExecutionService, positive_seconds
from promethee.hermes_adapter import REASONING_EFFORTS, validate_chat_options
from promethee.runtime import Runtime
from promethee.world import ActionError


@contextlib.contextmanager
def exclusive_host(data_dir):
    """OS-owned lock releases on a crash; the pathname is never a stale-lock test."""
    with (Path(data_dir) / "conversation.lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("A conversation host already owns this session.") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def prepare_profile(profile, data_dir, turn_id, *, vault=None, call_authority=False):
    if type(call_authority) is not bool:
        raise ValueError("Call authority must be explicitly enabled or disabled.")
    profile.mkdir(parents=True, exist_ok=False)
    (profile / "vault").mkdir()
    config = {
        "tools": {"tool_search": {"enabled": "off"}},
        "mcp_servers": {
            "promethee": {
                "command": sys.executable,
                "args": [
                    "-m",
                    "promethee.mcp_server",
                    "--data-dir",
                    str(data_dir),
                    "--turn-id",
                    turn_id,
                ],
                "timeout": 10,
                "tools": {
                    "include": [
                        "read_world",
                        "list_capabilities",
                        "submit_action",
                        "read_execution",
                        "cancel_action",
                    ],
                    "resources": False,
                    "prompts": False,
                },
            }
        },
    }
    if vault is not None:
        server = config["mcp_servers"]["promethee"]
        server["args"][-2:-2] = ["--vault", str(vault)]
        server["tools"]["include"].extend(
            ["search_memory", "read_memory_note", "read_memory_source", "write_memory_note"]
        )
    if call_authority:
        config["mcp_servers"]["promethee"]["args"][-2:] = ["--call-authority"]
    (profile / "config.yaml").write_text(json.dumps(config), encoding="utf-8")


class WorkerProcess:
    """One bounded private JSON exchange, with an interruptible owned subprocess."""

    def __init__(self, command, request, *, prewarm=False, lifetime=120):
        payload = json.dumps(request, ensure_ascii=False, allow_nan=False) + "\n"
        if len(payload) > 1_048_576:
            raise ValueError("Conversation request is too large.")
        self.results = queue.Queue(maxsize=1)
        self.prewarm = prewarm
        self.setup = dict(request) if prewarm else None
        self.started = time.monotonic()
        self.expires_at = self.started + positive_seconds(lifetime)
        self.ready = threading.Event()
        self.activation = threading.Event()
        self.activation_payload = None
        self.ready_seconds = None
        self.closed = False
        self.expired = False
        self._lock = threading.RLock()
        self.timer = None
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            creationflags=(subprocess.CREATE_NO_WINDOW | 4) if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        self.job = None
        if os.name == "nt":
            from promethee.windows_job import WindowsJob

            try:
                self.job = WindowsJob(self.process)
                self.job.resume(self.process.pid)
            except Exception:
                if self.job:
                    self.job.close()
                self.process.kill()
                self.process.wait(timeout=5)
                self.process.stdin.close()
                self.process.stdout.close()
                raise
        self.reader = threading.Thread(target=self._exchange, args=(payload,), daemon=True)
        self.reader.start()
        if prewarm:
            self.timer = threading.Timer(lifetime, self._expire)
            self.timer.daemon = True
            self.timer.start()

    def _expire(self):
        with self._lock:
            if not self.activation.is_set():
                self.expired = True
                self.close()

    def warm_status(self):
        if self.expired:
            return {"state": "expired"}
        if self.closed or self.process.poll() is not None:
            return {"state": "failed"}
        if self.ready.is_set():
            return {"state": "ready", "prewarm_seconds": self.ready_seconds}
        if not self.results.empty():
            return {"state": "failed"}
        return {"state": "preparing"}

    def activate(self, request):
        """One message and fresh history, only after the host has activated its turn."""
        if not self.prewarm:
            raise ValueError("This worker was not prepared.")
        payload = json.dumps(request, ensure_ascii=False, allow_nan=False) + "\n"
        expected = {k: v for k, v in self.setup.items() if k != "standby_seconds"}
        with self._lock:
            if (
                not self.prewarm
                or self.activation.is_set()
                or self.warm_status()["state"] not in {"ready", "preparing"}
                or time.monotonic() >= self.expires_at
                or len(payload) > 1_048_576
                or {k: v for k, v in request.items() if k not in {"message", "history"}} != expected
            ):
                raise ValueError("Prepared worker is expired, used or bound to another request.")
            if self.timer:
                self.timer.cancel()
            self.activation_payload = payload
            self.activation.set()
        return self

    def _exchange(self, payload):
        try:
            self.process.stdin.write(payload)
            self.process.stdin.flush()
            if self.prewarm:
                line = self.process.stdout.readline(4_194_305)
                if len(line) > 4_194_304 or not line.endswith("\n"):
                    raise ValueError("Invalid preparation response.")
                ready = json.loads(line)
                if ready != {
                    "type": "ready",
                    "turn_id": self.setup["turn_id"],
                    "session_id": self.setup["session_id"],
                }:
                    raise ValueError("Worker did not prepare the expected turn and session.")
                self.ready_seconds = time.monotonic() - self.started
                self.ready.set()
                self.activation.wait()
                if self.activation_payload is None:
                    raise ValueError("Prepared worker was discarded.")
                self.process.stdin.write(self.activation_payload)
            self.process.stdin.close()
            line = self.process.stdout.readline(4_194_305)
            if len(line) > 4_194_304 or not line.endswith("\n"):
                raise ValueError("Invalid worker response.")
            result = json.loads(line)
            if not isinstance(result, dict):
                raise ValueError("Invalid worker response.")
            if self.process.stdout.read(1) or self.process.wait(timeout=5) != 0:
                raise ValueError("Worker did not finish cleanly.")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            result = {"type": "error", "code": "worker_failure"}
        self.results.put(result)

    def poll(self):
        try:
            return self.results.get_nowait()
        except queue.Empty:
            return None

    def close(self):
        with self._lock:
            if self.closed:
                return
            self.closed = True
            if self.timer:
                self.timer.cancel()
            self.activation.set()  # Release a reader waiting for an unused reservation.
            if self.job:
                self.job.close()
            elif os.name != "nt":
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait(timeout=5)
            self.reader.join(timeout=2)
            if self.reader.is_alive():
                raise RuntimeError("Conversation worker pipes did not close.")
            with contextlib.suppress(OSError):
                self.process.stdin.close()
            self.process.stdout.close()


class ResidentProcess(WorkerProcess):
    """One serialized native agent; only successful completed turns may reuse it."""

    resident = True

    def __init__(self, command, request, *, lifetime=120):
        self.requests = queue.Queue(maxsize=1)
        self.current_turn = None
        self.used_turns = set()
        self.idle_lifetime = lifetime
        super().__init__(command, request, prewarm=True, lifetime=lifetime)

    def _frame(self):
        line = self.process.stdout.readline(4_194_305)
        if len(line) > 4_194_304 or not line.endswith("\n"):
            raise ValueError("Invalid resident response.")
        result = json.loads(line)
        if not isinstance(result, dict):
            raise ValueError("Invalid resident response.")
        return result

    def _exchange(self, payload):
        try:
            self.process.stdin.write(payload)
            self.process.stdin.flush()
            if self._frame() != {
                "type": "ready",
                "turn_id": self.setup["turn_id"],
                "session_id": self.setup["session_id"],
            }:
                raise ValueError("Resident prepared a different turn or session.")
            self.ready_seconds = time.monotonic() - self.started
            self.ready.set()
            while (payload := self.requests.get()) is not None:
                self.process.stdin.write(payload)
                self.process.stdin.flush()
                result = self._frame()
                if result.get("type") == "result" and result.get("turn_id") != self.current_turn:
                    raise ValueError("Resident returned a different turn.")
                self.results.put_nowait(result)
                if (
                    result.get("type") != "result"
                    or result.get("failed")
                    or result.get("interrupted")
                ):
                    return
        except (OSError, ValueError, queue.Full):
            with contextlib.suppress(queue.Full):
                self.results.put_nowait({"type": "error", "code": "worker_failure"})

    def warm_status(self):
        status = super().warm_status()
        if status["state"] in {"ready", "preparing"} and self.current_turn is not None:
            return {"state": "active"}
        return status

    def activate(self, request):
        payload = json.dumps(request, ensure_ascii=False, allow_nan=False) + "\n"
        expected = {k: v for k, v in self.setup.items() if k not in {"standby_seconds", "turn_id"}}
        actual = {k: v for k, v in request.items() if k not in {"message", "history", "turn_id"}}
        turn_id = request.get("turn_id")
        with self._lock:
            if (
                self.current_turn is not None
                or self.warm_status()["state"] not in {"ready", "preparing"}
                or time.monotonic() >= self.expires_at
                or len(payload) > 1_048_576
                or actual != expected
                or not isinstance(turn_id, str)
                or turn_id in self.used_turns
                or (not self.used_turns and turn_id != self.setup["turn_id"])
            ):
                raise ValueError("Resident is busy, expired or bound to different settings.")
            if self.timer:
                self.timer.cancel()
            self.current_turn = turn_id
            self.used_turns.add(turn_id)
            self.activation.set()
            self.requests.put_nowait(payload)
        return self

    def release_turn(self):
        """Called only after the trusted host commits the matching successful result."""
        with self._lock:
            if self.closed or self.current_turn is None:
                raise ValueError("Resident no longer owns a completed turn.")
            self.current_turn = None
            self.activation.clear()
            self.expires_at = time.monotonic() + self.idle_lifetime
            self.timer = threading.Timer(self.idle_lifetime, self._expire)
            self.timer.daemon = True
            self.timer.start()

    def close(self):
        with contextlib.suppress(queue.Full):
            self.requests.put_nowait(None)
        super().close()


class TextHost:
    """The UI serializes start/poll/close; only the pipe reader runs in a thread."""

    def __init__(
        self,
        store,
        factory,
        *,
        model,
        base_url,
        api_mode,
        timeout=60,
        reasoning_effort=None,
        measure_timing=False,
        prewarm_factory=None,
        prewarm_lifetime=120,
        system_message=None,
        resident=False,
    ):
        validate_chat_options(reasoning_effort, measure_timing)
        if type(resident) is not bool:
            raise ValueError("Resident mode must be explicitly enabled or disabled.")
        if system_message is not None and (
            not isinstance(system_message, str)
            or not system_message.strip()
            or len(system_message) > 16000
        ):
            raise ValueError("Expected a nonempty system message of at most 16000 characters.")
        self.store, self.factory = store, factory
        self.prewarm_lifetime = positive_seconds(prewarm_lifetime)
        if self.prewarm_lifetime > 300:
            raise ValueError("A prepared worker may live for at most 300 seconds.")
        self.prewarm_factory = prewarm_factory
        self.resident_mode = resident
        self.resident_worker = None
        self.spare = self.reservation = None
        self.worker_wrapper = lambda worker, request: worker
        self.settings = {"model": model, "base_url": base_url, "api_mode": api_mode}
        if system_message is not None:
            self.settings["system_message"] = system_message
        if reasoning_effort is not None:
            self.settings["reasoning_effort"] = reasoning_effort
        self.measure_timing = measure_timing
        if measure_timing:
            self.settings["measure_timing"] = True
        self.timeout = positive_seconds(timeout)
        self.worker, self.turn_id = None, None
        self.pending_result = None
        self.initiative_turn = None
        store.recover()

    def _discard_spare(self):
        if self.spare:
            self.spare.close()
        self.spare = self.reservation = None
        self.store.discard_reservation()

    def warm_status(self):
        """Nonblocking status; never starts inference or activates a turn."""
        if self.prewarm_factory is None:
            return {"state": "disabled"}
        if self.resident_worker is not None:
            status = self.resident_worker.warm_status()
            if status["state"] in {"expired", "failed"}:
                self.resident_worker.close()
                self.resident_worker = None
            return status
        if self.spare is None:
            return {"state": "idle"}
        status = self.spare.warm_status()
        if self.store.service.clock() >= self.reservation.expires_at:
            status = {"state": "expired"}
        if status["state"] in {"expired", "failed"}:
            self._discard_spare()
        return status

    def warm(self):
        """Explicitly prepare at most one next turn, without reading its future history."""
        status = self.warm_status()
        if status["state"] in {"disabled", "preparing", "ready", "active"}:
            return status
        reservation = self.store.reserve_turn(lifetime=self.prewarm_lifetime)
        try:
            self.spare = self.prewarm_factory(
                {
                    **self.settings,
                    "turn_id": reservation.turn_id,
                    "session_id": reservation.session_id,
                    "standby_seconds": self.prewarm_lifetime,
                }
            )
            self.reservation = reservation
        except Exception:
            self._discard_spare()
            raise
        return self.warm_status()

    def start(self, message, *, source="user"):
        started = time.monotonic()
        usable = self.warm_status()["state"] in {"ready", "preparing"}
        reusable = self.resident_worker if usable and self.worker is None else None
        try:
            opened = self.store.begin(
                message,
                timeout=self.timeout,
                trigger=source,
                reservation=self.reservation if usable and reusable is None else None,
            )
        except ReservationExpired:
            self._discard_spare()
            usable = False
            opened = self.store.begin(message, timeout=self.timeout, trigger=source)
        prepared = reusable or (self.spare if usable else None)
        if reusable:
            self.resident_worker = None
        if usable:
            self.spare = self.reservation = None
        self.initiative_turn = None
        return self._launch(opened, message, started, prepared=prepared)

    def _launch(self, opened, message, started, *, prepared=None):
        self.pending_result = None
        if self.measure_timing:
            self.timing_started = time.perf_counter()
        # Fence the old tools BEFORE stopping their process or starting a new one.
        self.turn_id = opened["turn_id"]
        self.deadline = started + self.timeout
        request = {**opened, **self.settings, "message": message}
        try:
            if self.worker:
                self.worker.close()
                self.worker = None
                self.resident_worker = None
            elif prepared is None and self.resident_worker is not None:
                prepared, self.resident_worker = self.resident_worker, None
            if prepared is None:
                self._discard_spare()
                worker = self.factory(request)
            else:
                try:
                    worker = prepared.activate(request)
                except ValueError:
                    # No payload was sent. Preserve this input as an unanswered
                    # turn; never reuse the profile or infer under a replacement ID.
                    self.store.abort(self.turn_id)
                    prepared.close()
                    self.pending_result = {
                        "status": "failed",
                        "code": "prepared_worker_unavailable",
                    }
                    return self.turn_id
            self.worker = worker
            if self.resident_mode and isinstance(worker, ResidentProcess):
                self.resident_worker = worker
            self.worker = self.worker_wrapper(worker, request)
        except Exception:
            self.store.abort(self.turn_id)
            if prepared:
                prepared.close()
            if self.worker:
                self.worker.close()
                self.worker = None
                self.resident_worker = None
            raise
        return self.turn_id

    def initiative_tick(self, *, allow_start=True):
        from promethee.initiative import Initiative

        initiative = Initiative(self.store.service)
        state = initiative.observe()
        if state is None:
            return None
        if state["paused"] and self.initiative_turn:
            self.cancel()
            self.initiative_turn = None
            return {"paused": True}
        if not allow_start or self.worker is not None:
            return None
        started = time.monotonic()
        opened = initiative.open_turn(self.store, timeout=self.timeout)
        if opened is None:
            return None
        message = opened.pop("message")
        self.initiative_turn = opened["turn_id"]
        self._launch(opened, message, started)
        return {"started": self.turn_id}

    def poll(self):
        if self.pending_result is not None:
            result, self.pending_result = self.pending_result, None
            return self._timed_result(result)
        if self.worker is None:
            return None
        if time.monotonic() >= self.deadline:
            self.cancel()
            return self._timed_result({"status": "failed", "code": "deadline_exceeded"})
        result = self.worker.poll()
        if result is None:
            return None
        completed_worker = self.worker
        resident = self.resident_worker
        if resident is None:
            completed_worker.close()
        self.worker = None
        timings = {}
        try:
            if self.measure_timing and isinstance(result, dict):
                raw = result.get("timings", {})
                allowed = {
                    "import_seconds",
                    "auth_seconds",
                    "agent_construct_seconds",
                    "run_conversation_seconds",
                    "mcp_shutdown_seconds",
                    "worker_total_seconds",
                    "prewarm_seconds",
                    "standby_wait_seconds",
                    "activation_seconds",
                    "auth_recheck_seconds",
                    "mcp_rebind_seconds",
                }
                if (
                    not isinstance(raw, dict)
                    or not set(raw) <= allowed
                    or any(
                        type(value) not in (int, float) or not math.isfinite(value) or value < 0
                        for value in raw.values()
                    )
                ):
                    raise ValueError("Invalid worker timing measurements.")
                timings = dict(raw)
            text = self.store.finish(self.turn_id, result)
        except ActionError:
            self.store.abort(self.turn_id, status="interrupted")
            if resident:
                completed_worker.close()
                self.resident_worker = None
            return self._timed_result(
                {"status": "interrupted", "code": "obsolete_response"}, timings
            )
        except ValueError:
            self.store.abort(self.turn_id)
            if resident:
                completed_worker.close()
                self.resident_worker = None
            return self._timed_result(
                {"status": "failed", "code": "model_or_worker_failure"}, timings
            )
        if resident:
            resident.release_turn()
        return self._timed_result({"status": "completed", "text": text}, timings)

    def _timed_result(self, result, timings=None):
        if self.measure_timing:
            # Includes subprocess startup, polling and cleanup, from _launch.
            result["timings"] = {
                **(timings or {}),
                "host_total_seconds": time.perf_counter() - self.timing_started,
            }
        return result

    def cancel(self):
        """Fence and stop the active turn; preserve the unactivated spare."""
        self.pending_result = None
        if self.turn_id:
            self.store.abort(self.turn_id, status="interrupted")
            self.turn_id = None
        if self.worker:
            self.worker.close()
            self.worker = None
            self.resident_worker = None

    def close(self):
        """Dispose active and prepared processes; safe to call repeatedly."""
        try:
            self.cancel()
        finally:
            self._discard_spare()
            if self.resident_worker:
                self.resident_worker.close()
                self.resident_worker = None


def configure(parser):
    parser.add_argument("--hermes-python", type=Path, required=True)
    parser.add_argument("--hermes-root", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url")
    parser.add_argument("--auth", choices=["api-key", "hermes-codex"], default="api-key")
    parser.add_argument(
        "--hermes-auth-root",
        type=Path,
        help="Existing Hermes root whose authentication is shared with fresh native profiles.",
    )
    parser.add_argument(
        "--api-mode", choices=["chat_completions", "codex_responses"], required=True
    )
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--reasoning-effort", choices=REASONING_EFFORTS)
    parser.add_argument("--measure-timing", action="store_true")
    parser.add_argument("--prewarm", action="store_true", help="Prepare one disposable next turn.")
    parser.add_argument("--resident", action="store_true", help="Reuse one isolated native agent.")
    parser.add_argument("--vault", type=Path, help="Optional sourced interactive memory vault.")


@contextlib.contextmanager
def open_text_host(args):
    reasoning_effort = getattr(args, "reasoning_effort", None)
    measure_timing = getattr(args, "measure_timing", False)
    prewarm = getattr(args, "prewarm", False)
    resident = getattr(args, "resident", False)
    if type(resident) is not bool:
        raise ValueError("Resident mode must be explicitly enabled or disabled.")
    if type(prewarm) is not bool:
        raise ValueError("Prewarming must be explicitly enabled or disabled.")
    prewarm = prewarm or resident
    validate_chat_options(reasoning_effort, measure_timing)
    auth = getattr(args, "auth", "api-key")
    auth_root = getattr(args, "hermes_auth_root", None)
    if resident and auth != "hermes-codex":
        raise ValueError("Resident mode currently requires native Hermes Codex authentication.")
    if auth not in {"api-key", "hermes-codex"}:
        raise ValueError("Unknown authentication mode.")
    if auth == "api-key" and not os.environ.get("PROMETHEE_OPENAI_API_KEY"):
        raise ValueError("Configure PROMETHEE_OPENAI_API_KEY locally before starting the chat.")
    from promethee.hermes_adapter import CODEX_BASE_URL

    base_url = args.base_url or (
        CODEX_BASE_URL if auth == "hermes-codex" else "https://api.openai.com/v1"
    )
    if auth == "hermes-codex":
        if auth_root is None or not auth_root.is_dir():
            raise ValueError(
                "Select the existing Hermes authentication root with --hermes-auth-root."
            )
        if base_url != CODEX_BASE_URL or args.api_mode != "codex_responses":
            raise ValueError(
                "Hermes ChatGPT authentication requires codex_responses and its official endpoint."
            )
    if not args.hermes_python.is_file() or not args.hermes_root.is_dir():
        raise ValueError("The configured Hermes Python and installation must exist.")
    data_dir = args.data_dir.resolve()
    runtime = Runtime(data_dir / "world.sqlite3", create=False)
    store = ConversationStore(ExecutionService(runtime))
    vault = args.vault.resolve() if args.vault is not None else None
    if vault is not None:
        from promethee.memory import MemoryStore

        MemoryStore(store.service, vault)
    worker_script = Path(__file__).with_name("hermes_worker.py").resolve()

    def factory(request, *, preparing=False):
        profile = data_dir / "conversation-profiles" / request["turn_id"]
        if auth == "hermes-codex":
            profile = auth_root.resolve() / "profiles" / ("promethee-" + request["turn_id"])
        prepare_profile(profile, data_dir, request["turn_id"], vault=vault, call_authority=resident)
        command = [
            str(args.hermes_python.resolve()),
            "-X",
            "utf8",
            str(worker_script),
            "--hermes-root",
            str(args.hermes_root.resolve()),
            "--profile",
            str(profile),
            "--auth",
            auth,
        ]
        if resident:
            setup = (
                request
                if preparing
                else {k: v for k, v in request.items() if k not in {"message", "history"}}
                | {"standby_seconds": 120}
            )
            process = ResidentProcess(
                [*command, "--resident"], setup, lifetime=setup["standby_seconds"]
            )
            if not preparing:
                process.activate(request)
            return process
        if preparing:
            return WorkerProcess(
                [*command, "--prewarm"], request, prewarm=True, lifetime=request["standby_seconds"]
            )
        return WorkerProcess(command, request)

    with exclusive_host(data_dir):
        host = TextHost(
            store,
            factory,
            model=args.model,
            base_url=base_url,
            api_mode=args.api_mode,
            timeout=args.timeout,
            reasoning_effort=reasoning_effort,
            measure_timing=measure_timing,
            prewarm_factory=(lambda request: factory(request, preparing=True)) if prewarm else None,
            system_message=getattr(args, "system_message", None),
            resident=resident,
        )
        try:
            if prewarm:
                host.warm()
            yield host
        finally:
            host.close()


def run_chat(args):
    incoming = queue.Queue(maxsize=16)

    def read_input():
        while True:
            line = sys.stdin.readline(16002)
            incoming.put(line)
            if not line:
                return

    with open_text_host(args) as host:
        threading.Thread(target=read_input, daemon=True).start()
        print(
            "Texte : un message par ligne. /cancel coupe la réponse ; /quit ferme le chat. "
            "/pause et /resume contrôlent l'initiative configurée.",
            flush=True,
        )
        try:
            while True:
                try:
                    line = incoming.get_nowait()
                except queue.Empty:
                    line = None
                if line is not None:
                    if not line or line.strip() == "/quit":
                        break
                    if line.strip() == "/cancel":
                        host.cancel()
                    elif line.strip() in {"/pause", "/resume"}:
                        from promethee.initiative import Initiative

                        state = Initiative(host.store.service).update(
                            paused=line.strip() == "/pause"
                        )
                        print(json.dumps({"initiative": state}), flush=True)
                    elif line.strip():
                        if not line.endswith("\n") or len(line.rstrip("\r\n")) > 16000:
                            raise ValueError("Input line exceeds 16000 characters.")
                        host.start(line.rstrip("\r\n"))
                    # Process another queued correction before emitting a result.
                    continue
                host.initiative_tick()
                result = host.poll()
                if result:
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                    if getattr(args, "prewarm", False):
                        host.warm()
                time.sleep(0.05)
        finally:
            host.close()
