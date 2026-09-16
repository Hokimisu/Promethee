"""Experimental Hermes / live ARDY / streaming Vox with optional local microphone."""

import argparse
import collections
import contextlib
import hashlib
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

from asr import ASRProcess, validate_audio
from body import BodyAdapter
from configuration import load_configuration
from delivery import DirectedWorker
from dialogue import instructions
from speech_text import prepare_speech_text

from promethee.chat import open_text_host
from promethee.initiative import Initiative
from promethee.memory import MemoryStore, initialize_vault
from promethee.world import ActionError

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
        self.mode = config.get("mode", "qualification")
        self._body_viewing = False
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
        self.asr = None
        self.asr_status = {"state": "disabled", "error": None}
        self.input_capture = None
        self.input_ids = set()
        self.pending_audio = None
        self.auto_continue = False
        self.turn_source = None
        self.turn_id = None
        self.output_deadline = 0
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
        world_dir = (
            config["world_dir"]
            if self.mode == "pet"
            else config.get("resume_world") or self.output / "world"
        )
        resume = (
            (world_dir / "world.sqlite3").is_file()
            if self.mode == "pet"
            else config.get("resume_world") is not None
        )
        self.body = BodyAdapter(
            data_dir=world_dir,
            resume=resume,
            session_kind="interactive" if self.mode == "pet" else "qualification",
            avatar=config["avatar"],
            **config["body"],
        )
        self.initiative = Initiative(self.body.service)
        if self.mode == "pet":
            vault = config["vault"]
            if not vault.exists() and not resume:
                initialize_vault(self.body.service.runtime, vault)
            MemoryStore(self.body.service, vault)
            if not resume and config.get("initiative") is not None:
                self.initiative.configure(**config["initiative"])
                # Configuration does not constitute an audience or an audio gesture.
                self.initiative.update(paused=True)
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
                "mode": getattr(self, "mode", "qualification"),
                "pet": {
                    **self.body.catalog(),
                    "command_revision": (body.get("world") or {}).get("command_revision"),
                    "viewing": time.monotonic() < self.output_deadline,
                }
                if getattr(self, "mode", "qualification") == "pet"
                else None,
                "ready": self.vox_ready and bool(body["ready"]),
                "motion": body.get("motion"),
                "body_state": body.get("state"),
                "world": body.get("world"),
                "body_error": body.get("error"),
                "body_presence": body.get("presence"),
                "asr": dict(self.asr_status),
                "initiative": self.body.service.runtime.snapshot()["initiative"],
                "turn_source": self.turn_source,
                "input": None
                if self.input_capture is None
                else {k: v for k, v in self.input_capture.items() if k != "audio_sha256"},
                "cursor": self.cursor,
                "elapsed_seconds": max(0, time.monotonic() - self.began)
                if getattr(self, "began", None)
                else 0,
            }

    def post(self, operation, value):
        if operation in ("pet", "pet_watch"):
            return self._post_pet(operation, value)
        if operation == "start" and getattr(self, "mode", "qualification") == "pet":
            raise ValueError("Le mode pet s’ouvre sans scénario ni limite de 60 secondes.")
        if operation in ("initiative_configure", "initiative_pause", "initiative_budget"):
            return self._post_initiative(operation, value)
        if operation in ("input_start", "input_audio", "input_cancel"):
            return self._post_input(operation, value)
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
            if self.turn_id:
                self.host.store.abort(self.turn_id, status="interrupted")
            if operation == "stop":
                self._pause_initiative()
                if getattr(self, "mode", "qualification") == "pet":
                    self.output_deadline = 0
                    self._set_pet_viewing(False)
            else:
                self.output_deadline = time.monotonic() + 15
            # Fence output immediately, before model/pipe cleanup in the owner loop.
            self.sid = sid
            self.state.update(
                session_id=sid, phase="thinking" if operation != "stop" else "stopping"
            )
            return {"session_id": sid, "cursor": self.cursor, "stopped": operation == "stop"}

    def _set_pet_viewing(self, enabled):
        if getattr(self, "mode", "qualification") == "pet" and enabled != self._body_viewing:
            self.body.set_viewing(enabled)
            self._body_viewing = enabled

    def _post_pet(self, operation, value):
        if getattr(self, "mode", "qualification") != "pet":
            raise ValueError("Cette interaction nécessite le mode pet.")
        with self.lock:
            if not self.vox_ready or not self.body.poll()["ready"]:
                raise ValueError("La voix et le corps se préparent encore.")
            if operation == "pet_watch":
                if value:
                    raise ValueError("L’ouverture ne reçoit aucun scénario.")
                if not self.sid:
                    self.sid = self.active_sid = uuid4().hex
                    self.state["session_id"] = self.sid
                self.output_deadline = time.monotonic() + 15
                state = self.initiative.service.runtime.snapshot()["initiative"]
                self._set_pet_viewing(not state or not state["paused"])
                return {
                    "session_id": self.sid,
                    "cursor": self.cursor,
                    "initiative": state,
                    "interrupted": False,
                }
            if not self.sid or time.monotonic() >= self.output_deadline:
                raise ValueError("Ouvre la boîte avant d’intervenir.")
            # Owner cleanup cannot consume this fence while this lock is held.
            # On refusal or replay the SID stays unchanged, so cleanup is skipped.
            sid = uuid4().hex
            self.commands.put_nowait(("pet_intervention", {"session_id": sid}))
            result = self.body.intervene(value)
            # A late grab cleanup may belong to an older browser interaction;
            # releasing that grab must not invalidate a newer spoken user turn.
            cleanup = (value.get("action") or {}).get("kind") == "grab_cancel"
            interrupted = not result.get("replayed", False) and not cleanup
            if interrupted:
                if self.turn_id:
                    self.host.store.abort(self.turn_id, status="interrupted")
                self.sid = sid
                self.state.update(session_id=sid, phase="stopping")
            return {
                **result,
                "session_id": self.sid,
                "cursor": self.cursor,
                "interrupted": interrupted,
            }

    def _pause_initiative(self):
        if self.initiative.service.runtime.snapshot()["initiative"] is not None:
            self.initiative.update(paused=True)

    def _autonomous_output(self):
        return self.turn_source == "initiative" and bool(
            self.host.worker
            or self.host.pending_result
            or self.pending_text
            or (self.speech and not self.speech.get("terminal", False))
            or (self.running and not self.speech)
        )

    def _initiative_paused_output(self):
        return self.turn_source == "initiative" and bool(
            self.initiative.service.runtime.snapshot()["initiative"]["paused"]
            or (
                getattr(self, "mode", "qualification") == "pet"
                and time.monotonic() >= self.output_deadline
            )
        )

    def _post_initiative(self, operation, value):
        with self.lock:
            if operation == "initiative_budget":
                if getattr(self, "mode", "qualification") != "pet":
                    raise ValueError("La recharge du budget nécessite le mode pet.")
                if set(value) != {"add_budget"} or value["add_budget"] is None:
                    raise ValueError("Indique le nombre de décisions à ajouter au budget.")
                state = self.initiative.update(add_budget=value["add_budget"])
                return {
                    "initiative": state,
                    "session_id": self.sid,
                    "cursor": self.cursor,
                    "interrupted": False,
                }
            interrupted = False
            if operation == "initiative_configure":
                if set(value) != {"budget", "interval"}:
                    raise ValueError("Indique un budget et une cadence explicites.")
                state = self.initiative.configure(**value)
            else:
                if set(value) != {"paused"} or type(value["paused"]) is not bool:
                    raise ValueError("La pause doit être un booléen.")
                interrupted = (
                    value["paused"] and self.active_sid == self.sid and self._autonomous_output()
                )
                sid = uuid4().hex if interrupted else self.sid
                if interrupted:
                    # Reserve owner cleanup before changing durable authority or the SID.
                    self.commands.put_nowait((operation, {"session_id": sid}))
                state = self.initiative.update(paused=value["paused"])
                if interrupted:
                    self.sid = sid
                    self.state.update(session_id=sid, phase="stopping")
            if not state["paused"]:
                if not self.sid:
                    self.sid = self.active_sid = uuid4().hex
                    self.state["session_id"] = self.sid
                # The browser invokes this only after its explicit audio gesture.
                self.output_deadline = time.monotonic() + 15
            self._set_pet_viewing(not state["paused"] and time.monotonic() < self.output_deadline)
            return {
                "initiative": state,
                "session_id": self.sid,
                "cursor": self.cursor,
                "interrupted": interrupted,
            }

    def _poll_initiative(self):
        with self.lock:
            state = self.initiative.observe()
            absent = time.monotonic() >= self.output_deadline
            self._set_pet_viewing(not absent and (state is None or not state["paused"]))
        if state is None:
            return
        with self.lock:
            pause_sid = (
                self.sid
                if (state["paused"] or (getattr(self, "mode", "qualification") == "pet" and absent))
                and self.active_sid == self.sid
                and self._autonomous_output()
                else None
            )
        if pause_sid is not None:
            # Process cleanup is owned here, never by a browser request thread.
            self.interrupt(body=False, expected_sid=pause_sid)
            with self.lock:
                if self.sid == pause_sid:
                    self.running = False
                    self.turn_source = None
                    self.host.initiative_turn = None
                    self.update(
                        phase="idle",
                        status="Initiative en pause"
                        if state["paused"]
                        else "En attente de présence",
                    )
            return
        with self.lock:
            capture = self.input_capture
            if (
                state["paused"]
                or not state["remaining"]
                or not self.sid
                or self.active_sid != self.sid
                or time.monotonic() >= self.output_deadline
                or (self.auto_continue and self.began and time.monotonic() - self.began >= 60)
                or not self.vox_ready
                or not self.body.poll()["ready"]
                or (capture and capture["state"] in {"listening", "transcribing"})
                or (self.asr is not None and self.asr.busy)
                or self.pending_audio
                or self.host.worker
                or self.host.pending_result
                or self.pending_text
                or self.speech
            ):
                return
            started = time.monotonic()
            result = self.host.initiative_tick()
            if result and result.get("started"):
                self.brain_started = started
                self.turn_id = result["started"]
                self.turn_source = "initiative"
                self.running = True
                self.calls += 1
                self.update(turn_id=self.turn_id, phase="thinking", status="Ariane réfléchit…")

    def _post_input(self, operation, value):
        input_id = value.get("input_id")
        if (
            not isinstance(input_id, str)
            or not input_id.startswith("input-")
            or not 7 <= len(input_id) <= 80
            or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in input_id)
        ):
            raise ValueError("Identifiant de prise de parole invalide.")
        # Decode before taking the publication lock. Audio is never written to disk.
        digest = (
            hashlib.sha256(validate_audio(value)).hexdigest()
            if operation == "input_audio"
            else None
        )
        with self.lock:
            capture = self.input_capture
            if operation == "input_start":
                if capture and capture["input_id"] == input_id:
                    if capture["session_id"] != self.sid:
                        raise ValueError("Cette prise de parole est périmée.")
                    return {"session_id": self.sid, "cursor": self.cursor, "input_id": input_id}
                if input_id in self.input_ids or len(self.input_ids) >= 256:
                    raise ValueError("Cette prise de parole ne peut pas être réutilisée.")
                if not self.asr or self.asr.state != "ready" or not self.snapshot()["ready"]:
                    raise ValueError(
                        "La transcription locale n’est pas prête. Le texte reste disponible."
                    )
                sid = uuid4().hex
                started = time.monotonic()
                self.commands.put_nowait((operation, {"session_id": sid, "input_id": input_id}))
                # The owner may be cleaning a worker. Fence durable MCP authority
                # before acknowledging input; never join its process on HTTP threads.
                if self.turn_id:
                    self.host.store.abort(self.turn_id, status="interrupted")
                self.sid = sid
                self.output_deadline = time.monotonic() + 15
                self.input_ids.add(input_id)
                self.input_capture = {
                    "input_id": input_id,
                    "session_id": sid,
                    "state": "listening",
                    "started_at": started,
                    "deadline": started + 18,
                    "fence_seconds": time.monotonic() - started,
                }
                self.pending_audio = None
                self.state.update(
                    session_id=sid, phase="listening", status="Je t’écoute…", error=None
                )
                return {"session_id": sid, "cursor": self.cursor, "input_id": input_id}
            if (
                not capture
                or capture["input_id"] != input_id
                or capture["session_id"] != value.get("session_id")
                or self.sid != value.get("session_id")
            ):
                raise ValueError("Cette prise de parole est périmée.")
            if operation == "input_audio":
                if "audio_sha256" in capture:
                    if digest != capture["audio_sha256"]:
                        raise ValueError("Cette prise de parole contient déjà un autre audio.")
                    return {
                        "ok": True,
                        "session_id": self.sid,
                        "input_id": input_id,
                        "replayed": True,
                    }
                if capture["state"] != "listening" or time.monotonic() >= capture["deadline"]:
                    raise ValueError("La prise de parole est terminée ou périmée.")
                self.commands.put_nowait((operation, dict(value)))
                capture.update(
                    state="transcribing", audio_sha256=digest, deadline=time.monotonic() + 40
                )
                self.state.update(phase="transcribing", status="Transcription…")
            else:
                if capture["state"] in {"cancelled", "failed"}:
                    return {
                        "ok": True,
                        "session_id": self.sid,
                        "input_id": input_id,
                        "replayed": True,
                    }
                if capture["state"] == "completed":
                    raise ValueError("Cette prise de parole est déjà traitée.")
                self.commands.put_nowait((operation, dict(value)))
                capture["state"] = "cancelled"
            return {"ok": True, "session_id": self.sid, "input_id": input_id}

    def _handle_input(self, operation, value):
        # Called only by the owner after checking session_id. Cleanup may block,
        # so every later publication must check the session again.
        if operation == "input_start":
            self.interrupt(body=False, notify=False)
            with self.lock:
                if value["session_id"] != self.sid:
                    return
                self.running = False
                self.auto_continue = False
                self.began = None
        elif operation == "input_audio":
            with self.lock:
                if (
                    value["session_id"] == self.sid
                    and self.input_capture["state"] == "transcribing"
                ):
                    self.pending_audio = value
        else:
            with self.lock:
                if value["session_id"] != self.sid:
                    return
                self.pending_audio = None
                self.running = False
                self.update(phase="idle", status="Prête")

    def _poll_input(self):
        if not self.asr:
            return
        event = self.asr.poll()
        with self.lock:
            self.asr_status = {"state": self.asr.state, "error": self.asr.error}
            capture = self.input_capture
            if (
                capture
                and capture["session_id"] == self.sid
                and capture["state"] in {"listening", "transcribing"}
            ):
                if time.monotonic() >= capture["deadline"] or self.asr.state == "failed":
                    capture["state"] = "failed"
                    self.pending_audio = None
                    self.running = False
                    self.update(
                        phase="idle",
                        status="Prête",
                        input_error="Écoute interrompue. Tu peux écrire.",
                    )
            if event and event.get("event") in {"transcript", "error"}:
                if (
                    capture
                    and capture["session_id"] == self.sid == event.get("id")
                    and capture["state"] == "transcribing"
                ):
                    text = event.get("text")
                    if (
                        event["event"] == "transcript"
                        and isinstance(text, str)
                        and 1 <= len(text.strip()) <= 1200
                    ):
                        capture["state"] = "completed"
                        capture["metrics"] = event.get("metrics", {})
                        self.running = True
                        self.update(transcript=text.strip(), input_error=None)
                        self.think(text.strip(), expected_sid=self.sid)
                    else:
                        capture["state"] = "failed"
                        self.running = False
                        self.update(
                            phase="idle",
                            status="Prête",
                            input_error="Parole non transcrite. Tu peux réessayer ou écrire.",
                        )
            if self.pending_audio and self.asr.state == "ready" and not self.asr.busy:
                value, self.pending_audio = self.pending_audio, None
                if (
                    value["session_id"] == self.sid
                    and capture
                    and capture["state"] == "transcribing"
                ):
                    self.asr.submit(value["session_id"], value["pcm16"])

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

    def interrupt(self, *, body=False, notify=True, expected_sid=None):
        self.host.cancel()
        self.pending_text = None
        if self.speech:
            self.vox_send({"op": "cancel", "id": self.speech["id"]})
            self.receipt("interrupted")
        self.speech = None
        with contextlib.suppress(RuntimeError):
            self.body.set_presence(False)
        with self.lock:
            if expected_sid is not None and expected_sid != self.sid:
                return
            if notify:
                self.emit("stop", body=body)
            if body:
                with contextlib.suppress(RuntimeError):
                    self.body.cancel()

    def think(self, text, first=False, *, expected_sid=None):
        with self.lock:
            if self.active_sid != self.sid or (
                expected_sid is not None and expected_sid != self.sid
            ):
                return
            prompt = ("Contexte de départ : " if first else "Message : ") + text
            self.brain_started = time.monotonic()
            self.turn_id = self.host.start(prompt)
            self.turn_source = "user"
            self.calls += 1
            self.update(turn_id=self.turn_id, phase="thinking", status="Ariane improvise…")

    def speak(self, item):
        with self.lock:
            if (
                self.active_sid != self.sid
                or item["sid"] != self.sid
                or self._initiative_paused_output()
            ):
                return
            self._speak_current(item)

    def _speak_current(self, item):
        prepared = prepare_speech_text(
            item["text"], STYLE + " Performance direction: " + item["delivery"]
        )
        self.body.set_presence(True)
        # The body command can wait for its owner; an external CLI pause can
        # become durable during that wait even while HTTP publication is locked.
        if self._initiative_paused_output():
            return
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
        self.metric["brain_backend"] = self.config.get("brain", "hermes")
        self.metric["world_context"] = self.config.get("world_context", False)
        try:
            if self.config.get("asr_command"):
                self._asr_log = (self.output / "asr.log").open("a", encoding="utf-8")
                try:
                    self.asr = ASRProcess(self.config["asr_command"], self._asr_log)
                    self.asr_status = {"state": "loading", "error": None}
                except Exception:
                    self.asr_status = {
                        "state": "failed",
                        "error": "Transcription locale indisponible. Le texte reste disponible.",
                    }
            args = SimpleNamespace(
                data_dir=self.body.data_dir,
                world_context=self.config.get("world_context", False),
                hermes_python=self.config.get("hermes_python"),
                hermes_root=self.config.get("hermes_root"),
                hermes_auth_root=self.config.get("hermes_auth_root"),
                model=self.model,
                auth="hermes-codex",
                api_mode="codex_responses",
                base_url=None,
                vault=self.config.get("vault") if self.mode == "pet" else None,
                timeout=90,
                reasoning_effort="low",
                measure_timing=True,
                system_message=instructions(self.mode),
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
                if self.config.get("brain") == "direct":
                    from direct_host import open_direct_host

                    context = open_direct_host(args, auth_file=self.config["auth_file"])
                else:
                    context = open_text_host(args)
                with context as self.host:
                    self.host.worker_wrapper = lambda worker, request: DirectedWorker(
                        worker,
                        request["turn_id"],
                        self.deliveries,
                        allow_silence=self.mode == "pet"
                        or self.host.initiative_turn == request["turn_id"],
                    )
                    self.loop()
        except Exception as exc:
            (self.output / "server-error.log").write_text(traceback.format_exc(), encoding="utf-8")
            self.update(status="Essai indisponible : " + str(exc), phase="error", error=str(exc))
        finally:
            if self.asr:
                self.asr.close()
            if hasattr(self, "_asr_log"):
                self._asr_log.close()
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
                    with self.lock:
                        if value.get("session_id") == self.sid:
                            if value.get("event") == "client_stats":
                                self.output_deadline = time.monotonic() + 15
                            with (self.output / "playback.jsonl").open(
                                "a", encoding="utf-8"
                            ) as log:
                                log.write(
                                    json.dumps({"at": time.time(), **value}, ensure_ascii=False)
                                    + "\n"
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
                if operation.startswith("input_"):
                    self._handle_input(operation, value)
                    continue
                self.interrupt(
                    body=operation in ("start", "stop"),
                    notify=operation in ("stop", "initiative_pause", "pet_intervention"),
                    expected_sid=value["session_id"],
                )
                with self.lock:
                    if value["session_id"] != self.sid:
                        continue
                    self.pending_audio = None
                    if self.input_capture and self.input_capture["state"] in {
                        "listening",
                        "transcribing",
                    }:
                        self.input_capture["state"] = "cancelled"
                    if operation in ("stop", "initiative_pause", "pet_intervention"):
                        self.running = False
                        if operation == "stop":
                            self.auto_continue = False
                            self.began = None
                        self.turn_source = None
                        self.host.initiative_turn = None
                        self.update(
                            status={
                                "stop": "Essai arrêté",
                                "initiative_pause": "Initiative en pause",
                                "pet_intervention": "Prête",
                            }[operation],
                            phase="idle",
                            text="",
                        )
                        continue
                    self.running = True
                    self.auto_continue = operation == "start" or (
                        getattr(self, "auto_continue", True) and self.began is not None
                    )
                    self.began = None if operation == "start" else self.began
                    self.calls = 0 if operation == "start" else self.calls
                    self.scenario = value.get("scenario", getattr(self, "scenario", ""))
                    self.think(
                        value.get("scenario", value.get("text")),
                        first=operation == "start",
                        expected_sid=value["session_id"],
                    )

            self._poll_input()
            self._poll_initiative()

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
                with self.lock:
                    current = self.speech
                    if (
                        not current
                        or event.get("id") != current["id"]
                        or current["sid"] != self.sid
                        or self._initiative_paused_output()
                    ):
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
            with self.lock:
                if result and self.active_sid == self.sid and not self._initiative_paused_output():
                    self.metric["brain_seconds"].append(time.monotonic() - self.brain_started)
                    if result.get("timings"):
                        self.metric["brain_timings"].append(result["timings"])
                    directed = self.turn_id in self.deliveries
                    delivery = self.deliveries.pop(self.turn_id, None)
                    if (
                        result["status"] == "completed"
                        and self.running
                        and self.active_sid == self.sid
                    ):
                        text = result["text"].strip()
                        if len(text) > 1000:
                            self.update(status="Réponse trop longue pour cet essai", phase="error")
                            self.running = False
                        elif not directed:
                            self.update(status="Direction vocale absente", phase="error")
                            self.running = False
                        elif delivery is None:
                            self.running = False
                            self.host.initiative_turn = None
                            self.update(status="Prête", phase="idle", text="")
                        else:
                            self.pending_text = {
                                "id": uuid4().hex,
                                "turn_id": self.turn_id,
                                "text": text,
                                "delivery": delivery,
                                "sid": self.active_sid,
                                "source": self.turn_source,
                            }
                    elif result["status"] != "completed":
                        self.update(
                            status="Ariane n’a pas terminé sa réponse",
                            phase="error",
                            error=result.get("code"),
                        )
                        self.running = False

            now = time.monotonic()
            if (
                self.active_sid == self.sid
                and getattr(self, "auto_continue", True)
                and self.began
                and now - self.began >= 60
            ):
                expired_sid = self.active_sid
                with self.lock:
                    if expired_sid == self.sid:
                        self._pause_initiative()
                self.interrupt(body=True, expected_sid=expired_sid)
                with self.lock:
                    if self.sid == expired_sid:
                        self.running = False
                        self.auto_continue = False
                        self.update(status="Essai de 60 secondes terminé", phase="idle")
            with self.lock:
                if self.active_sid == self.sid:
                    if self.speech and self.speech["done"]:
                        if (
                            self.speech["terminal"]
                            or now > (self.speech["end_estimate"] or now) + 2
                        ):
                            # Without an actual browser receipt, do not claim successful playback.
                            if not self.speech["terminal"]:
                                self.receipt("interrupted")
                            self.speech = None
                    if self.running and not self.speech and self.pending_text:
                        pending, self.pending_text = self.pending_text, None
                        self.speak(pending)
                    if (
                        self.running
                        and not self.speech
                        and not self.pending_text
                        and not self.host.worker
                    ):
                        with contextlib.suppress(RuntimeError):
                            self.body.set_presence(False)
                        self.running = False
                        self.host.initiative_turn = None
                        self.update(status="Prête", phase="idle")
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
    for name, mime in {
        "vad.worklet.bundle.min.js": "text/javascript",
        "silero_vad_v5.onnx": "application/octet-stream",
        "ort-wasm-simd-threaded.mjs": "text/javascript",
        "ort-wasm-simd-threaded.wasm": "application/wasm",
    }.items():
        assets["/vad/" + name] = (mime, HERE / "web/vad" / name)

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
            if self.path not in (
                "/start",
                "/say",
                "/stop",
                "/telemetry",
                "/input_start",
                "/input_audio",
                "/input_cancel",
                "/initiative_configure",
                "/initiative_pause",
                "/initiative_budget",
                "/pet_watch",
                "/pet",
            ):
                self.close_connection = True
                return self.send(404, {"error": "Unknown route"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                limit = 520000 if self.path == "/input_audio" else 16384
                if not 0 < length <= limit or self.headers.get("Transfer-Encoding"):
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
            except (ValueError, ActionError, queue.Full) as exc:
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
        print("Local session logs: " + str(owner.output), flush=True)
        server.serve_forever()
    finally:
        if owner is not None:
            owner.stopping.set()
        server.server_close()
        if owner is not None:
            owner.thread.join(45)


if __name__ == "__main__":
    main()
