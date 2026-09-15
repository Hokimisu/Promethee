"""Bounded bidirectional pipes for the isolated Live SDK worker."""

import contextlib
import json
import os
import queue
import signal
import subprocess
import threading

from promethee.live_worker import LIMIT, command


class LiveProcess:
    def __init__(self, argv):
        self.incoming, self.outgoing = queue.Queue(maxsize=64), queue.Queue(maxsize=8)
        self.stopped, self.read_done = threading.Event(), threading.Event()
        self.error, self.ending, self.exited = None, False, False
        self.job = None
        self.process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=(subprocess.CREATE_NO_WINDOW | 4) if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        try:
            if os.name == "nt":
                from promethee.windows_job import WindowsJob

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
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.writer = threading.Thread(target=self._write, daemon=True)
        self.reader.start()
        self.writer.start()

    def _read(self):
        try:
            while not self.stopped.is_set():
                line = self.process.stdout.readline(LIMIT + 1)
                if not line:
                    return
                if len(line) > LIMIT or not line.endswith(b"\n"):
                    raise ValueError("Invalid transport line.")
                event = json.loads(line)
                if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                    raise ValueError("Invalid transport event.")
                while not self.stopped.is_set():
                    try:
                        self.incoming.put(event, timeout=0.1)
                        break
                    except queue.Full:
                        continue
        except Exception:
            self.error = "live_pipe_read_failed"
        finally:
            self.read_done.set()

    def _write(self):
        try:
            while not self.stopped.is_set():
                try:
                    payload = self.outgoing.get(timeout=0.1)
                except queue.Empty:
                    continue
                if payload is None:
                    self.process.stdin.close()
                    return
                self.process.stdin.write(payload)
                self.process.stdin.flush()
        except Exception:
            self.error = "live_pipe_write_failed"

    def send(self, event):
        if self.ending or self.stopped.is_set():
            raise ValueError("Live input is closed.")
        payload = json.dumps(command(event), ensure_ascii=False, allow_nan=False).encode() + b"\n"
        try:
            self.outgoing.put_nowait(payload)
        except queue.Full as exc:
            raise ValueError("Live input backpressure limit reached.") from exc

    def finish(self):
        """EOF requests graceful finalization after already queued commands."""
        if not self.ending:
            self.outgoing.put_nowait(None)
            self.ending = True

    def poll(self):
        if self.error:
            raise ValueError(self.error)
        try:
            return self.incoming.get_nowait()
        except queue.Empty:
            code = self.process.poll()
            if code is not None and self.read_done.is_set() and not self.exited:
                self.exited = True
                return {"type": "transport.exited", "returncode": code}
            return None

    def close(self):
        if self.stopped.is_set():
            return
        self.stopped.set()
        if self.job:
            self.job.close()
        elif os.name != "nt":
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGKILL)
        self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        self.writer.join(timeout=2)
        if self.reader.is_alive() or self.writer.is_alive():
            raise RuntimeError("Live worker pipes did not close.")
        with contextlib.suppress(OSError):
            self.process.stdin.close()
        self.process.stdout.close()
