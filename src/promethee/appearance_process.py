"""One cancellable appearance preparation, with validation off the body loop."""

import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from promethee.prepared_avatar import MAX_BYTES


class AppearancePreparation:
    """Submit, poll, cancel and close from the single owning body-loop thread."""

    def __init__(self, *, avatar, script, output, node="node", timeout=60):
        if not 0 < timeout <= 60:
            raise ValueError("Appearance preparation timeout must be within 60 seconds.")
        self.avatar, self.script = Path(avatar).resolve(), Path(script).resolve()
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.node, self.timeout = str(node), timeout
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="appearance")
        self.future = None
        self.pending = None
        self.cancelled = threading.Event()
        self.closed = False

    def submit(self, document, *, mode):
        if self.closed or self.pending is not None:
            raise RuntimeError("Appearance preparation is closed or busy.")
        if mode not in ("--plant", "--settle"):
            raise ValueError("Unknown appearance preparation mode.")
        # Freeze caller-owned data before handing it to another thread.
        payload = json.dumps(document, allow_nan=False).encode("utf-8")
        if len(payload) > MAX_BYTES:
            raise ValueError("Appearance motion document exceeds 32 MiB.")
        job_id = uuid4().hex
        self.cancelled.clear()
        self.future = self.executor.submit(self._prepare, job_id, payload, mode)
        self.pending = job_id
        return job_id

    def _prepare(self, job_id, payload, mode):
        folder = self.output / job_id
        folder.mkdir(exist_ok=False)
        motion = folder / "motion.json"
        motion.write_bytes(payload)
        poses = folder / "poses.json"
        validated = folder / "validated.json"
        started = time.monotonic()
        commands = [
            [
                self.node,
                str(self.script),
                str(self.avatar),
                str(motion),
                str(folder / "measurement.json"),
                mode,
                "--poses",
                str(poses),
            ],
            [
                sys.executable,
                "-m",
                "promethee.prepared_avatar",
                "--poses",
                str(poses),
                "--motion",
                str(motion),
                "--output",
                str(validated),
            ],
        ]
        for stage, command in zip(("geometry", "validation"), commands, strict=True):
            if not self._run(command, folder / f"{stage}-stderr.txt", started):
                return None
        with validated.open("rb") as stream:
            payload = stream.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            raise ValueError("Validated appearance output exceeds 32 MiB.")
        result = json.loads(payload)
        return None if self.cancelled.is_set() else result

    def _run(self, command, stderr_path, started):
        process = None
        try:
            if self.cancelled.is_set():
                return False
            with stderr_path.open("xb") as stderr:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=stderr,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                while process.poll() is None:
                    if self.cancelled.wait(0.02):
                        return False
                    if time.monotonic() - started > self.timeout:
                        raise TimeoutError("Appearance preparation exceeded its time limit.")
                if self.cancelled.is_set():
                    return False
                if process.returncode != 0:
                    raise ValueError(f"Appearance {stderr_path.stem} failed; inspect its report.")
            if time.monotonic() - started > self.timeout:
                raise TimeoutError("Appearance preparation exceeded its time limit.")
            return True
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)

    def poll(self):
        if self.future is None or not self.future.done():
            return None
        job_id, future = self.pending, self.future
        self.pending = self.future = None
        # Cancellation wins even if a completed result was waiting to be polled.
        if self.cancelled.is_set():
            return {"type": "cancelled", "job_id": job_id}
        try:
            result = future.result()
        except Exception as exc:
            return {"type": "error", "job_id": job_id, "error": str(exc)}
        return {"type": "prepared", "job_id": job_id, "appearance": result}

    def cancel(self):
        if self.pending is not None:
            self.cancelled.set()

    def close(self):
        if not self.closed:
            self.closed = True
            self.cancel()
            self.executor.shutdown(wait=True, cancel_futures=True)
            self.pending = self.future = None
