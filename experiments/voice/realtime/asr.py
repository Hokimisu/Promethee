"""Bounded, optional local transcription process; audio stays in memory."""

import base64
import binascii
import contextlib
import json
import os
import queue
import subprocess
import threading
import time

MAX_PCM_BYTES = 12 * 16000 * 2
MAX_RESPONSE_CHARS = 200000  # 16,000 Unicode characters escaped as ASCII plus metadata.


def validate_audio(value):
    if type(value.get("sample_rate")) is not int or value["sample_rate"] != 16000:
        raise ValueError("Le microphone doit fournir du PCM mono à 16 kHz.")
    encoded = value.get("pcm16")
    if not isinstance(encoded, str) or not 4 <= len(encoded) <= MAX_PCM_BYTES * 4 // 3:
        raise ValueError("Une prise de parole doit durer au plus 12 secondes.")
    try:
        pcm = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Audio invalide.") from exc
    if not 2 <= len(pcm) <= MAX_PCM_BYTES or len(pcm) % 2:
        raise ValueError("Audio PCM16 invalide.")
    return pcm


class ASRProcess:
    """One in-flight job, no retries, with a bounded writer and response queue."""

    def __init__(self, command, log, *, clock=time.monotonic):
        self.clock = clock
        self.state, self.error = "loading", None
        self.active_id = None
        self.started = clock()
        self.deadline = self.started + 60
        self.events = queue.Queue(maxsize=4)
        self.requests = queue.Queue(maxsize=1)
        self.closed = threading.Event()
        self.job = None
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) | 4)
            if os.name == "nt"
            else 0,
        )
        if os.name == "nt":
            from promethee.windows_job import WindowsJob

            try:
                self.job = WindowsJob(self.process)
                self.job.resume(self.process.pid)
            except Exception:
                self.process.kill()
                self.process.wait(timeout=5)
                if self.job:
                    self.job.close()
                raise
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.writer = threading.Thread(target=self._write, daemon=True)
        self.reader.start()
        self.writer.start()

    @property
    def busy(self):
        return self.active_id is not None

    def _emit(self, value):
        while not self.closed.is_set():
            try:
                self.events.put(value, timeout=0.1)
                return
            except queue.Full:
                pass

    def _read(self):
        try:
            while not self.closed.is_set():
                line = self.process.stdout.readline(MAX_RESPONSE_CHARS + 1)
                if not line:
                    break
                if len(line) > MAX_RESPONSE_CHARS or not line.endswith("\n"):
                    raise ValueError("Oversized ASR response")
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("Invalid ASR response")
                self._emit(value)
        except (ValueError, OSError, RecursionError):
            pass
        self._emit({"event": "worker_exit"})

    def _write(self):
        try:
            while not self.closed.is_set():
                try:
                    value = self.requests.get(timeout=0.1)
                except queue.Empty:
                    continue
                self.process.stdin.write(json.dumps(value, ensure_ascii=False) + "\n")
                self.process.stdin.flush()
        except (ValueError, OSError):
            self._emit({"event": "worker_exit"})

    def submit(self, capture_id, pcm16):
        if not isinstance(capture_id, str) or not capture_id.strip() or len(capture_id) > 80:
            raise ValueError("Invalid transcription identifier.")
        validate_audio({"sample_rate": 16000, "pcm16": pcm16})
        if self.closed.is_set() or self.state != "ready" or self.busy:
            raise ValueError("La transcription n’est pas disponible.")
        self.requests.put_nowait(
            {
                "op": "transcribe",
                "id": capture_id,
                "sample_rate": 16000,
                "pcm16": pcm16,
            }
        )
        self.active_id = capture_id
        self.deadline = self.clock() + 30

    def poll(self):
        if self.state == "failed" or self.closed.is_set():
            return None
        if (self.busy or self.state == "loading") and self.clock() >= self.deadline:
            self.error = "La transcription locale a dépassé son délai. Le texte reste disponible."
            active = self.active_id
            self.close()
            self.state = "failed"
            return {"event": "error", "id": active, "message": self.error}
        try:
            value = self.events.get_nowait()
        except queue.Empty:
            return None
        event = value.get("event")
        try:
            json.dumps(value, allow_nan=False)
        except (ValueError, TypeError):
            event = None
        if event == "transcript" and (
            not isinstance(value.get("text"), str)
            or len(value["text"]) > 16000
            or not isinstance(value.get("metrics"), dict)
        ):
            event = None
        if event == "ready" and value.get("id") is None and self.state == "loading":
            self.state = "ready"
            return value
        if (
            self.active_id is not None
            and event in {"transcript", "error"}
            and value.get("id") == self.active_id
        ):
            self.active_id = None
            return value
        if event == "worker_exit" or event == "error":
            self.error = "La transcription locale est indisponible. Le texte reste disponible."
            active = self.active_id
            self.close()
            self.state = "failed"
            return {"event": "error", "id": active, "message": self.error}
        self.error = "Réponse de transcription inattendue. Le texte reste disponible."
        self.close()
        self.state = "failed"
        return {"event": "error", "id": None, "message": self.error}

    def close(self):
        if self.closed.is_set():
            return
        self.closed.set()
        if self.job:
            self.job.close()
        elif self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        self.writer.join(timeout=2)
        with contextlib.suppress(OSError):
            self.process.stdin.close()
            self.process.stdout.close()
