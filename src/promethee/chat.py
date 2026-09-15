"""Exclusive text host for the native Hermes worker. No autonomous polling of a model."""

import contextlib
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from promethee.conversation import ConversationStore
from promethee.execution import ExecutionService, positive_seconds
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


def prepare_profile(profile, data_dir, turn_id, *, vault=None):
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
    (profile / "config.yaml").write_text(json.dumps(config), encoding="utf-8")


class WorkerProcess:
    """One bounded private JSON exchange, with an interruptible owned subprocess."""

    def __init__(self, command, request):
        payload = json.dumps(request, ensure_ascii=False, allow_nan=False) + "\n"
        if len(payload) > 1_048_576:
            raise ValueError("Conversation request is too large.")
        self.results = queue.Queue(maxsize=1)
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

    def _exchange(self, payload):
        try:
            self.process.stdin.write(payload)
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


class TextHost:
    """The UI serializes start/poll/close; only the pipe reader runs in a thread."""

    def __init__(self, store, factory, *, model, base_url, api_mode, timeout=60):
        self.store, self.factory = store, factory
        self.settings = {"model": model, "base_url": base_url, "api_mode": api_mode}
        self.timeout = positive_seconds(timeout)
        self.worker, self.turn_id = None, None
        store.recover()

    def start(self, message):
        started = time.monotonic()
        opened = self.store.begin(message, timeout=self.timeout)
        # Fence the old tools BEFORE stopping their process or starting a new one.
        self.turn_id = opened["turn_id"]
        self.deadline = started + self.timeout
        request = {**opened, **self.settings, "message": message}
        try:
            if self.worker:
                self.worker.close()
                self.worker = None
            self.worker = self.factory(request)
        except Exception:
            self.store.abort(self.turn_id)
            raise
        return self.turn_id

    def poll(self):
        if self.worker is None:
            return None
        if time.monotonic() >= self.deadline:
            self.close()
            return {"status": "failed", "code": "deadline_exceeded"}
        result = self.worker.poll()
        if result is None:
            return None
        self.worker.close()
        self.worker = None
        try:
            text = self.store.finish(self.turn_id, result)
        except ActionError:
            self.store.abort(self.turn_id, status="interrupted")
            return {"status": "interrupted", "code": "obsolete_response"}
        except ValueError:
            self.store.abort(self.turn_id)
            return {"status": "failed", "code": "model_or_worker_failure"}
        return {"status": "completed", "text": text}

    def close(self):
        if self.turn_id:
            self.store.abort(self.turn_id, status="interrupted")
        if self.worker:
            self.worker.close()
            self.worker = None


def configure(parser):
    parser.add_argument("--hermes-python", type=Path, required=True)
    parser.add_argument("--hermes-root", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="https://api.openai.com/v1")
    parser.add_argument(
        "--api-mode", choices=["chat_completions", "codex_responses"], required=True
    )
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--vault", type=Path, help="Optional sourced interactive memory vault.")


@contextlib.contextmanager
def open_text_host(args):
    if not os.environ.get("PROMETHEE_OPENAI_API_KEY"):
        raise ValueError("Configure PROMETHEE_OPENAI_API_KEY locally before starting the chat.")
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

    def factory(request):
        profile = data_dir / "conversation-profiles" / request["turn_id"]
        prepare_profile(profile, data_dir, request["turn_id"], vault=vault)
        return WorkerProcess(
            [
                str(args.hermes_python.resolve()),
                "-X",
                "utf8",
                str(worker_script),
                "--hermes-root",
                str(args.hermes_root.resolve()),
                "--profile",
                str(profile),
            ],
            request,
        )

    with exclusive_host(data_dir):
        host = TextHost(
            store,
            factory,
            model=args.model,
            base_url=args.base_url,
            api_mode=args.api_mode,
            timeout=args.timeout,
        )
        try:
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
            "Texte : un message par ligne. /cancel coupe la réponse ; /quit ferme le chat.",
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
                        host.close()
                    elif line.strip():
                        if not line.endswith("\n") or len(line.rstrip("\r\n")) > 16000:
                            raise ValueError("Input line exceeds 16000 characters.")
                        host.start(line.rstrip("\r\n"))
                    # Process another queued correction before emitting a result.
                    continue
                result = host.poll()
                if result:
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                time.sleep(0.05)
        finally:
            host.close()
