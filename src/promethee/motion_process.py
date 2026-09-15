"""One bounded process connection for the incompatible ARDY Python environment."""

import json
import os
import queue
import subprocess
import threading
import time
from contextlib import suppress
from pathlib import Path


class MotionProcess:
    def __init__(self, command, output, *, wsl=None):
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.wsl = wsl
        self.pid = None
        self.ready = False
        self.pending = None
        self.started_at = time.monotonic()
        self.messages = queue.Queue(maxsize=8)
        self.log = (self.output / "worker.log").open("ab")
        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self.log,
                text=True,
                encoding="utf-8",
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception:
            self.log.close()
            raise
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            while line := self.process.stdout.readline(65537):
                if len(line) > 65536 or not line.endswith("\n"):
                    raise ValueError("Oversized response from motion worker.")
                item = json.loads(line)
                if not isinstance(item, dict) or item.get("type") not in {
                    "started",
                    "ready",
                    "generated",
                    "error",
                }:
                    raise ValueError("Invalid response from motion worker.")
                self.messages.put(item)
            self.messages.put({"type": "crashed", "error": "Motion worker closed its output."})
        except (OSError, ValueError) as exc:
            self.messages.put({"type": "crashed", "error": str(exc)})

    def poll(self):
        try:
            item = self.messages.get_nowait()
        except queue.Empty:
            return None
        kind = item["type"]
        if kind == "started":
            pid = item.get("pid")
            if type(pid) is not int or pid <= 0:
                self.ready = False
                return {"type": "crashed", "error": "Invalid worker process identity."}
            self.pid = pid
        elif kind == "ready":
            self.ready = True
        elif kind in {"generated", "error"}:
            if item.get("job_id") != self.pending:
                self.ready = False
                return {"type": "crashed", "error": "Motion result does not match its request."}
            self.pending = None
        elif kind == "crashed":
            self.ready = False
        return item

    def submit(self, job):
        if not self.ready or self.pending is not None:
            raise RuntimeError("Motion worker is unavailable or busy.")
        line = json.dumps(job, allow_nan=False) + "\n"
        if len(line) > 65536:
            raise ValueError("Oversized motion request.")
        self.process.stdin.write(line)
        self.process.stdin.flush()
        self.pending = job["job_id"]
        self.started_at = time.monotonic()

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write('{"type":"shutdown"}\n')
                self.process.stdin.flush()
                self.process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                if self.wsl and self.pid:
                    # PID came from this worker's private stdout, not a process-name match.
                    with suppress(OSError, subprocess.TimeoutExpired):
                        subprocess.run(
                            ["wsl", "-d", self.wsl, "--exec", "kill", "-TERM", str(self.pid)],
                            check=False,
                            timeout=5,
                            capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                        )
                else:
                    self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
        # Windows can report EINVAL while flushing a pipe whose child has exited.
        with suppress(OSError):
            self.process.stdin.close()
        self.reader.join(timeout=1)
        self.process.stdout.close()
        self.log.close()


def start_ardy_process(
    *, python, checkpoint_root, output, wsl=None, encoder_url="http://127.0.0.1:9550"
):
    script = Path(__file__).with_name("ardy_worker.py").resolve()
    output = Path(output).resolve()

    def linux_path(path):
        return subprocess.check_output(
            ["wsl", "-d", wsl, "--exec", "wslpath", "-a", "-u", str(path)],
            text=True,
            encoding="utf-8",
        ).strip()

    prefix = ["wsl", "-d", wsl, "--exec"] if wsl else []
    command = prefix + [
        str(python),
        "-u",
        linux_path(script) if wsl else str(script),
        "--checkpoint-root",
        str(checkpoint_root),
        "--output",
        linux_path(output) if wsl else str(output),
        "--encoder-url",
        encoder_url,
    ]
    return MotionProcess(command, output, wsl=wsl)
