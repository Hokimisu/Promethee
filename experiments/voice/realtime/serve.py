"""Experimental Hermes / live ARDY / streaming Vox session, no microphone."""

import argparse
import collections
import contextlib
import json
import queue
import subprocess
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from body import BodyAdapter
from configuration import load_configuration
from delivery import DirectedWorker
from dialogue import instructions
from speech_text import prepare_speech_text

from promethee.chat import open_text_host

HERE = Path(__file__).resolve().parent
RATE = 48000
STYLE = (
    "A young adult woman speaking native metropolitan French. Warm clear feminine "
    "mid-register voice, slightly husky, intimate conversational delivery. "
    "Expressive and natural, with breaths and pauses, without shouting or singing."
)


class Session:
    def __init__(self, config):
        self.config = config
        self.output = config["data_dir"] / ("session-" + uuid4().hex[:12])
        self.output.mkdir(parents=True, exist_ok=False)
        self.lock = threading.RLock()
        self.commands = queue.Queue(maxsize=16)
        self.vox_events = queue.Queue(maxsize=128)
        self.events = collections.deque(maxlen=640)
        self.cursor = 0
        self.sid = ""
        self.active_sid = ""
        self.deliveries = {}
        self.vox_ready = False
        self.stopping = threading.Event()
        self.state = {
            "ready": False,
            "status": "Chargement de la voix et du corps…",
            "phase": "loading",
            "text": "",
            "session_id": "",
            "metrics": {},
        }
        self.port = config["port"]
        self.voice_profile = "configured-reference"
        self.model = config["model"]
        self.body = BodyAdapter(
            data_dir=self.output / "world", avatar=config["avatar"], **config["body"]
        )
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def emit(self, event, **fields):
        with self.lock:
            self.cursor += 1
            self.events.append(
                {"cursor": self.cursor, "session_id": self.sid, "event": event, **fields}
            )

    def update(self, **fields):
        with self.lock:
            self.state.update(fields)

    def snapshot(self):
        body = self.body.poll()
        with self.lock:
            return {
                **self.state,
                "ready": self.vox_ready and bool(body["ready"]),
                "motion": body.get("motion"),
                "body_state": body.get("state"),
                "world": body.get("world"),
                "body_error": body.get("error"),
                "body_presence": body.get("presence"),
                "cursor": self.cursor,
                "elapsed_seconds": max(0, time.monotonic() - self.began)
                if getattr(self, "began", None)
                else 0,
            }

    def post(self, operation, value):
        if operation in ("start", "say"):
            field = "scenario" if operation == "start" else "text"
            text = value.get(field)
            if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1200:
                raise ValueError("Écris un contexte ou une intervention de 1 à 1 200 caractères.")
            if not self.snapshot()["ready"]:
                raise ValueError("La voix et le corps se préparent encore.")
        if operation == "telemetry":
            self.commands.put_nowait((operation, value))
            return {"ok": True}
        with self.lock:
            sid = uuid4().hex
            self.commands.put_nowait((operation, {**value, "session_id": sid}))
            # Fence output immediately, before model/pipe cleanup in the owner loop.
            self.sid = sid
            self.state.update(
                session_id=sid, phase="thinking" if operation != "stop" else "stopping"
            )
            return {"session_id": sid, "cursor": self.cursor, "stopped": operation == "stop"}

    def vox_send(self, value):
        self.vox.stdin.write(json.dumps(value, ensure_ascii=False) + "\n")
        self.vox.stdin.flush()

    def read_vox(self):
        try:
            for line in self.vox.stdout:
                if len(line) > 100000:
                    raise ValueError("Oversized voice message")
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                self.vox_events.put(value)
        finally:
            self.vox_events.put({"event": "worker_exit"})

    def receipt(self, status, speech=None):
        item = speech or self.speech
        if item:
            try:
                self.host.store.speech_delivery(item["turn_id"], item["id"], status)
            except Exception:
                # Existing terminal receipts must never be overwritten.
                pass

    def interrupt(self, *, body=False, notify=True):
        self.host.cancel()
        self.pending_text = None
        if self.speech:
            self.vox_send({"op": "cancel", "id": self.speech["id"]})
            self.receipt("interrupted")
        self.speech = None
        with contextlib.suppress(RuntimeError):
            self.body.set_presence(False)
        if notify:
            self.emit("stop")
        if body:
            with contextlib.suppress(RuntimeError):
                self.body.cancel()

    def think(self, text, first=False):
        prompt = ("Contexte de départ : " if first else "Suite de la scène : ") + text
        self.brain_started = time.monotonic()
        self.turn_id = self.host.start(prompt)
        self.calls += 1
        self.update(turn_id=self.turn_id, phase="thinking", status="Ariane improvise…")

    def speak(self, item):
        with self.lock:
            if self.active_sid != self.sid or item["sid"] != self.sid:
                return
            self._speak_current(item)

    def _speak_current(self, item):
        prepared = prepare_speech_text(
            item["text"], STYLE + " Performance direction: " + item["delivery"]
        )
        self.body.set_presence(True)
        self.speech = {
            **item,
            "samples": 0,
            "first": None,
            "done": False,
            "end_estimate": None,
            "sid": self.sid,
            "terminal": False,
        }
        self.receipt("preparing")
        self.emit(
            "speech_start", id=item["id"], text=prepared["display_text"], delivery=item["delivery"]
        )
        self.update(
            text=prepared["display_text"], phase="synthesizing", status="Ariane prend la parole…"
        )
        self.vox_send(
            {
                "op": "speak",
                "id": item["id"],
                "text": prepared["spoken_text"],
                "style": prepared["style"],
            }
        )
        with (self.output / "delivery.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps({"at": time.time(), **item}, ensure_ascii=False) + "\n")

    def run(self):
        self.speech = None
        self.pending_text = None
        self.running = False
        self.began = None
        self.calls = 0
        self.next_metrics_write = 0
        self.next_brain_warm = 0
        self.turn_id = None
        self.metric = {
            "voice_runs": [],
            "brain_seconds": [],
            "brain_timings": [],
            "reasoning_effort": "low",
            "scope": "experimental live local session",
        }
        self.metric["voice_profile"] = self.voice_profile
        self.metric["dialogue_model"] = self.model
        try:
            args = SimpleNamespace(
                data_dir=self.body.data_dir,
                hermes_python=self.config["hermes_python"],
                hermes_root=self.config["hermes_root"],
                hermes_auth_root=self.config["hermes_auth_root"],
                model=self.model,
                auth="hermes-codex",
                api_mode="codex_responses",
                base_url=None,
                vault=None,
                timeout=90,
                reasoning_effort="low",
                measure_timing=True,
                system_message=instructions(),
                prewarm=True,
                resident=self.config["resident"],
            )
            self.body.start()
            with (self.output / "vox.log").open("a", encoding="utf-8") as log:
                self.vox = subprocess.Popen(
                    self.config["voice_command"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=log,
                    text=True,
                    encoding="utf-8",
                    bufsize=1,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                threading.Thread(target=self.read_vox, daemon=True).start()
                with open_text_host(args) as self.host:
                    self.host.worker_wrapper = lambda worker, request: DirectedWorker(
                        worker, request["turn_id"], self.deliveries
                    )
                    self.loop()
        except Exception as exc:
            (self.output / "server-error.log").write_text(traceback.format_exc(), encoding="utf-8")
            self.update(status="Essai indisponible : " + str(exc), phase="error", error=str(exc))
        finally:
            if hasattr(self, "vox"):
                with contextlib.suppress(Exception):
                    self.vox_send({"op": "shutdown"})
                    self.vox.wait(timeout=20)
            self.body.close()

    def loop(self):
        while not self.stopping.is_set():
            for _ in range(16):
                try:
                    operation, value = self.commands.get_nowait()
                except queue.Empty:
                    break
                if operation == "telemetry":
                    if value.get("session_id") == self.sid:
                        with (self.output / "playback.jsonl").open("a", encoding="utf-8") as log:
                            log.write(
                                json.dumps({"at": time.time(), **value}, ensure_ascii=False) + "\n"
                            )
                        if self.speech and value.get("id") == self.speech["id"]:
                            event = value.get("event")
                            if event == "playback_started":
                                self.receipt("playing")
                            elif event == "playback_finished":
                                self.receipt("completed")
                                self.speech["terminal"] = True
                            elif event == "playback_interrupted":
                                self.receipt("interrupted")
                    continue
                with self.lock:
                    current_command = value["session_id"] == self.sid
                    if current_command:
                        self.active_sid = value["session_id"]
                if not current_command:
                    continue
                self.interrupt(body=operation in ("start", "stop"), notify=operation == "stop")
                if operation == "stop":
                    self.running = False
                    self.update(status="Essai arrêté", phase="idle", text="")
                    continue
                self.running = True
                self.began = None if operation == "start" else self.began
                self.calls = 0 if operation == "start" else self.calls
                self.scenario = value.get("scenario", getattr(self, "scenario", ""))
                self.think(value.get("scenario", value.get("text")), first=operation == "start")

            for _ in range(64):
                try:
                    event = self.vox_events.get_nowait()
                except queue.Empty:
                    break
                kind = event.get("event")
                if kind == "ready":
                    self.vox_ready = True
                    self.update(status="Prête", phase="idle")
                    continue
                if kind == "worker_exit":
                    raise RuntimeError("Le moteur vocal s’est fermé.")
                if kind == "error" and event.get("id") is None:
                    raise RuntimeError(event.get("message", "Chargement vocal impossible"))
                current = self.speech
                if not current or event.get("id") != current["id"] or current["sid"] != self.sid:
                    continue
                if kind == "pcm":
                    now = time.monotonic()
                    if current["first"] is None:
                        current["first"] = now
                        if self.began is None:
                            self.began = now + 0.5
                    current["samples"] += event["samples"]
                    current["end_estimate"] = current["first"] + 0.5 + current["samples"] / RATE
                    self.emit("pcm", **{k: v for k, v in event.items() if k != "event"})
                    self.update(status="En scène", phase="speaking")
                elif kind == "done":
                    current["done"] = True
                    self.metric["voice_runs"].append(event.get("metrics", event))
                    self.emit("speech_end", id=current["id"])
                elif kind in ("error", "cancelled"):
                    self.receipt("failed" if kind == "error" else "interrupted")
                    self.emit("stop", id=current["id"])
                    self.speech = None
                    self.update(
                        status="Synthèse interrompue",
                        phase="error",
                        error=event.get("message", kind),
                    )

            result = self.host.poll()
            if result:
                self.metric["brain_seconds"].append(time.monotonic() - self.brain_started)
                if result.get("timings"):
                    self.metric["brain_timings"].append(result["timings"])
                delivery = self.deliveries.pop(self.turn_id, None)
                if result["status"] == "completed" and self.running and self.active_sid == self.sid:
                    text = result["text"].strip()
                    if len(text) > 1000:
                        self.update(status="Réponse trop longue pour cet essai", phase="error")
                        self.running = False
                    elif not delivery:
                        self.update(status="Direction vocale absente", phase="error")
                        self.running = False
                    else:
                        self.pending_text = {
                            "id": uuid4().hex,
                            "turn_id": self.turn_id,
                            "text": text,
                            "delivery": delivery,
                            "sid": self.active_sid,
                        }
                elif result["status"] != "completed":
                    self.update(
                        status="Ariane n’a pas terminé sa réponse",
                        phase="error",
                        error=result.get("code"),
                    )
                    self.running = False

            now = time.monotonic()
            if self.running and self.began and now - self.began >= 60:
                self.interrupt(body=True)
                self.running = False
                self.update(status="Essai de 60 secondes terminé", phase="idle")
            if self.speech and self.speech["done"]:
                if self.speech["terminal"] or now > (self.speech["end_estimate"] or now) + 2:
                    # Without an actual browser receipt, do not claim successful playback.
                    if not self.speech["terminal"]:
                        self.receipt("interrupted")
                    self.speech = None
            if self.running and not self.speech and self.pending_text:
                pending, self.pending_text = self.pending_text, None
                self.speak(pending)
            if (
                self.running
                and self.active_sid == self.sid
                and self.speech
                and self.speech["first"]
                and not self.host.worker
                and not self.pending_text
                and self.calls < 12
                and (not self.began or now - self.began < 54)
            ):
                self.think(
                    "Poursuis naturellement, sans répéter. Tiens compte du monde observé et "
                    "du contexte précédent. Une intervention utilisateur reste prioritaire."
                )
            if self.vox_ready and self.body.poll()["ready"] and not self.running:
                if self.state["phase"] == "loading":
                    self.update(status="Prête", phase="idle")
            preparation = self.host.warm_status()
            if preparation.get("state") == "failed":
                self.next_brain_warm = now + 30
            if now >= getattr(self, "next_brain_warm", 0):
                preparation = self.host.warm()
            self.metric["brain_preparation"] = preparation
            self.update(metrics=self.metric)
            if now >= self.next_metrics_write:
                (self.output / "metrics.json").write_text(
                    json.dumps(self.metric, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                self.next_metrics_write = now + 1
            time.sleep(0.02)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", type=Path, required=True, help="Machine-local JSON configuration."
    )
    args = parser.parse_args()
    config = load_configuration(args.config)
    if not (HERE / "web/bundle.js").is_file():
        parser.error(
            "Build the browser sources first: node experiments/voice/realtime/web/build.mjs"
        )
    assets = {
        "/": ("text/html; charset=utf-8", HERE / "web/index.html"),
        "/style.css": ("text/css", HERE / "web/style.css"),
        "/bundle.js": ("text/javascript", HERE / "web/bundle.js"),
        "/pcm-worklet.js": ("text/javascript", HERE / "web/pcm-worklet.js"),
        "/bundle.js.LEGAL.txt": ("text/plain; charset=utf-8", HERE / "web/bundle.js.LEGAL.txt"),
        "/avatar.vrm": ("model/gltf-binary", config["avatar"]),
    }

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        timeout = 10  # Bound idle keep-alive connections and incomplete request reads.
        disable_nagle_algorithm = True

        def send(self, code, value, mime="application/json"):
            raw = (
                value
                if isinstance(value, bytes)
                else json.dumps(value, ensure_ascii=False).encode("utf-8")
            )
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if self.close_connection:
                self.send_header("Connection", "close")
            self.end_headers()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(raw)

        def allowed(self, mutation=False):
            origin = "http://127.0.0.1:" + str(config["port"])
            return self.headers.get("Host") == origin[7:] and (
                not mutation or self.headers.get("Origin") == origin
            )

        def do_GET(self):
            if (
                self.headers.get("Transfer-Encoding")
                or self.headers.get("Content-Length", "0") != "0"
            ):
                self.close_connection = True
                return self.send(400, {"error": "GET requests must not have a body"})
            if not self.allowed():
                return self.send(403, {"error": "Unexpected host"})
            route = urlsplit(self.path)
            if route.path in assets:
                mime, path = assets[route.path]
                return self.send(200, path.read_bytes(), mime)
            if route.path == "/state.json":
                return self.send(200, owner.snapshot())
            if route.path == "/events":
                try:
                    after = int(parse_qs(route.query).get("after", ["0"])[0])
                except ValueError:
                    return self.send(400, {"error": "Invalid cursor"})
                with owner.lock:
                    events = [item for item in owner.events if item["cursor"] > after][:128]
                    return self.send(
                        200,
                        {
                            "session_id": owner.sid,
                            "events": events,
                            "cursor": events[-1]["cursor"] if events else owner.cursor,
                            "gap": bool(owner.events and after < owner.events[0]["cursor"] - 1),
                        },
                    )
            return self.send(404, {"error": "Unknown route"})

        def do_POST(self):
            if not self.allowed(True):
                self.close_connection = True
                return self.send(403, {"error": "Same-origin only"})
            if self.path not in ("/start", "/say", "/stop", "/telemetry"):
                self.close_connection = True
                return self.send(404, {"error": "Unknown route"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384 or self.headers.get("Transfer-Encoding"):
                    raise ValueError("Invalid message size")
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError("JSON required")
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError("Incomplete message body")
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise ValueError("Expected object")
                self.send(200, owner.post(self.path[1:], value))
            except (ValueError, queue.Full) as exc:
                # A rejected request may still have unread bytes; do not parse
                # them as the next request on a persistent connection.
                self.close_connection = True
                self.send(400, {"error": str(exc)})

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", config["port"]), Handler)
    owner = None
    try:
        owner = Session(config)
        print("Simulation: http://127.0.0.1:" + str(config["port"]), flush=True)
        print("Local qualification data: " + str(owner.output), flush=True)
        server.serve_forever()
    finally:
        if owner is not None:
            owner.stopping.set()
        server.server_close()
        if owner is not None:
            owner.thread.join(45)


if __name__ == "__main__":
    main()
