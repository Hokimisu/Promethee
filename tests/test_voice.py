"""Voice lifecycle with synthetic PCM and controlled providers; never opens a microphone."""

import base64
import copy
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from promethee.chat import TextHost, WorkerProcess
from promethee.conversation import ConversationStore
from promethee.execution import ExecutionService
from promethee.runtime import Runtime
from promethee.voice import INPUT_BYTES, AudioDevice, VoiceHost, decode_pcm
from promethee.world import ActionError

PCM = b"\x01\x00" * 2400


class Pending:
    def __init__(self, request):
        self.request, self.result, self.closed = request, None, False

    def poll(self):
        return self.result

    def close(self):
        self.closed = True


class Device:
    def __init__(self):
        self.active, self.error = False, None
        self.played = []
        self.stops = 0

    def listen(self):
        self.active = True

    def stop(self):
        self.stops += 1
        self.active = False

    def finish_recording(self):
        self.stop()
        return PCM

    def play(self, pcm):
        self.played.append(pcm)
        self.active = True


def setup(tmp_path):
    clock = [10.0]
    store = ConversationStore(
        ExecutionService(
            Runtime(
                tmp_path / "world.sqlite3", data_origin="session", session_kind="qualification"
            ),
            clock=lambda: clock[0],
        )
    )
    reasoning, audio = [], []

    def factory(workers):
        def create(request):
            worker = Pending(request)
            workers.append(worker)
            return worker

        return create

    text = TextHost(
        store, factory(reasoning), model="fixture", base_url="unused", api_mode="chat_completions"
    )
    device = Device()
    voice = VoiceHost(
        text,
        factory(audio),
        device,
        transcription_model="fixture-transcribe",
        speech_model="fixture-speech",
        voice="fixture",
        base_url="unused",
        timeout=5,
        clock=lambda: clock[0],
    )
    return voice, reasoning, audio, clock


def answer(worker, text="Fixture answer"):
    request = worker.request
    worker.result = {
        "type": "result",
        "turn_id": request["turn_id"],
        "failed": False,
        "interrupted": False,
        "text": text,
        "messages": [
            *request["history"],
            {"role": "user", "content": request["message"]},
            {"role": "assistant", "content": text},
        ],
    }


def audio_answer(worker, **payload):
    worker.result = {"type": "result", "generation": worker.request["generation"], **payload}


def test_recording_to_same_history_and_playback(tmp_path):
    host, reasoning, audio, clock = setup(tmp_path)
    host.listen()
    host.finish_listening()
    assert decode_pcm(audio[0].request["pcm"], 480000) == PCM
    audio_answer(audio[0], text="Fixture voice request")
    assert host.poll()["status"] == "transcribed"
    answer(reasoning[0])
    result = host.poll()
    assert result["status"] == "answered" and result["text"] == "Fixture answer"
    assert result["turn_id"] == reasoning[0].request["turn_id"]
    audio_answer(audio[1], pcm=base64.b64encode(PCM).decode())
    clock[0] += 2
    result = host.poll()
    assert result["status"] == "playback_started"
    assert result["seconds_to_playback"] == 2
    assert result["audio_seconds"] == 0.1 and result["billed_cost"] is None
    assert host.device.played == [PCM]
    host.device.active = False
    assert host.poll()["status"] == "playback_finished"
    host.text("Follow up in text")
    assert [m["content"] for m in reasoning[1].request["history"]] == [
        "Fixture voice request",
        "Fixture answer",
    ]
    host.interrupt()


def receipt(host):
    return host.text_host.store.service.get_world(include_executions=True)[
        "recent_speech_deliveries"
    ]["items"][0]["delivery"]


@pytest.mark.parametrize(
    "ending", ["completed", "interrupted", "failed", "restart", "preparing-stop"]
)
def test_delivery_receipt_survives_and_never_claims_heard_words(tmp_path, ending):
    host, reasoning, audio, _ = setup(tmp_path)
    host.text("Read this response")
    answer(reasoning[0])
    host.poll()
    assert receipt(host)["status"] == "preparing"
    if ending == "preparing-stop":
        host.interrupt()
    else:
        audio_answer(audio[0], pcm=base64.b64encode(PCM).decode())
        host.poll()
        assert receipt(host)["status"] == "playing"
        if ending == "restart":
            # Simulated crash: stop the device without issuing a terminal receipt.
            host.device.stop()
            ConversationStore(host.text_host.store.service).recover()
        elif ending == "interrupted":
            host.interrupt()
        else:
            host.device.active = False
            host.device.error = "speaker_underflow" if ending == "failed" else None
            host.poll()
    result = receipt(host)
    assert result["status"] == (
        "interrupted" if ending in {"restart", "preparing-stop"} else ending
    )
    assert result["playback_started"] == (ending != "preparing-stop")
    assert result["heard_by_user"] is None and result["heard_text"] is None
    service = host.text_host.store.service
    reopened = ExecutionService(Runtime(service.runtime.path, create=False))
    assert (
        reopened.get_world(include_executions=True)["recent_speech_deliveries"]["items"][0][
            "delivery"
        ]
        == result
    )
    assert service.events() == []


def test_delivery_generation_terminal_guard_and_source_status(tmp_path):
    host, reasoning, audio, _ = setup(tmp_path)
    host.text("Speak")
    answer(reasoning[0])
    host.poll()
    store = host.text_host.store
    turn, generation = host.delivery
    with pytest.raises(ActionError, match="generation"):
        store.speech_delivery(turn, "other-generation", "playing")
    with pytest.raises(ActionError, match="transition"):
        store.speech_delivery(turn, generation, "completed")
    audio[0].result = {"type": "error"}
    host.poll()
    assert receipt(host)["status"] == "failed"
    with pytest.raises(ActionError, match="terminal"):
        store.speech_delivery(turn, generation, "playing")
    assert store.speech_delivery(turn, generation, "failed") == receipt(host)


@pytest.mark.parametrize(
    "stage", ["listening", "transcribing", "thinking", "synthesizing", "speaking"]
)
def test_correction_cuts_each_stage_and_rejects_late_results(tmp_path, stage):
    host, reasoning, audio, _ = setup(tmp_path)
    host.listen()
    if stage != "listening":
        host.finish_listening()
    if stage in {"thinking", "synthesizing", "speaking"}:
        audio_answer(audio[0], text="Old request")
        host.poll()
    old_turn = host.text_host.turn_id
    if stage in {"synthesizing", "speaking"}:
        answer(reasoning[0])
        host.poll()
    if stage == "speaking":
        audio_answer(audio[-1], pcm=base64.b64encode(PCM).decode())
        host.poll()
    already_played = list(host.device.played)
    old_audio = list(audio)
    old_reasoning = list(reasoning)
    host.text("Corrected request")
    assert not host.device.active
    assert all(w.closed for w in old_audio + old_reasoning)
    for worker in old_audio:
        audio_answer(worker, text="Late request", pcm=base64.b64encode(PCM).decode())
    for worker in old_reasoning:
        answer(worker, "Late response")
    assert host.poll() is None
    assert host.device.played == already_played
    if old_turn:
        with pytest.raises(ActionError):
            host.text_host.store.service.end_turn(old_turn)
    assert len(reasoning) == len(old_reasoning) + 1
    host.interrupt()


def test_audio_interruption_preserves_active_body_action(tmp_path, articulated_pose):
    host, reasoning, _, _ = setup(tmp_path)
    service = host.text_host.store.service
    driver = service.acquire_controller(source="kinematic", supported_actions=["move"])
    world = service.runtime.snapshot()
    observed = {k: copy.deepcopy(world[k]) for k in ("avatar", "objects")}
    observed["pose"] = articulated_pose
    driver.reconcile(observed, stopped=True)
    host.text("Fixture pending response")
    service.submit(
        "moving",
        service.get_world()["revision"],
        {"kind": "move", "args": {"position": [0.2, 0.3]}},
    )
    driver.claim_next()
    before = service.get("moving")
    host.listen()
    assert reasoning[0].closed
    assert service.get("moving") == before
    assert not service.get("moving")["cancel_requested"]
    assert service.get_world()["pose"] == articulated_pose
    host.interrupt()


def test_provider_failure_timeout_wrong_generation_and_long_answer(tmp_path):
    host, reasoning, audio, clock = setup(tmp_path)
    host.listen()
    host.finish_listening()
    clock[0] += 6
    assert host.poll()["code"] == "audio_deadline_exceeded"
    assert audio[0].closed and not reasoning
    host.listen()
    host.finish_listening()
    audio[-1].result = {"type": "error"}
    assert host.poll()["status"] == "failed"
    host.listen()
    host.finish_listening()
    audio[-1].result = {"type": "result", "generation": "obsolete", "text": "Late"}
    assert host.poll()["status"] == "failed" and not reasoning
    host.text("Long answer")
    answer(reasoning[-1], "x" * 2001)
    result = host.poll()
    assert result["status"] == "text_only" and len(result["text"]) == 2001
    assert host.state == "idle" and not host.device.played
    host.interrupt()


def test_microphone_absent_is_explicit_without_starting_a_request(monkeypatch, tmp_path):
    class Absent:
        def RawInputStream(self, **kwargs):
            raise OSError("No device")

    monkeypatch.setitem(sys.modules, "sounddevice", Absent())
    host, reasoning, audio, _ = setup(tmp_path)
    host.device = AudioDevice()
    with pytest.raises(ValueError, match="Microphone unavailable"):
        host.listen()
    assert not reasoning and not audio
    host.interrupt()


def test_device_callbacks_bound_capture_and_finish_output_without_hardware(monkeypatch):
    class Stop(Exception):
        pass

    class Stream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]
            self.active = False
            self.closed = False

        def start(self):
            self.active = True

        def abort(self):
            self.active = False

        def close(self):
            self.closed = True

    class Module:
        CallbackStop = CallbackAbort = Stop
        RawInputStream = RawOutputStream = Stream

    monkeypatch.setitem(sys.modules, "sounddevice", Module())
    device = AudioDevice()
    device.listen()
    microphone = device.stream
    with pytest.raises(Stop):
        microphone.callback(b"\x00\x00" * INPUT_BYTES, INPUT_BYTES, None, False)
    assert len(device.buffer) == INPUT_BYTES
    assert len(device.finish_recording()) == INPUT_BYTES
    assert microphone.closed
    device.play(PCM)
    speaker = device.stream
    output = bytearray(len(PCM) + 100)
    with pytest.raises(Stop):
        speaker.callback(output, len(output) // 2, None, False)
    assert output == PCM + b"\0" * 100
    device.stop()
    assert speaker.closed


def test_real_audio_worker_against_local_http_fixture(monkeypatch):
    pytest.importorskip("openai")
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            requests.append((self.path, body))
            if "/denied/" in self.path:
                self.send_error(401, "Provider private diagnostic must not reach output")
                return
            if self.path.endswith("transcriptions"):
                assert b"RIFF" in body and b"recording.wav" in body
                content, kind = b'{"text":"Fixture transcript"}', "application/json"
            else:
                payload = json.loads(body)
                assert payload["response_format"] == "pcm" and payload["input"] == "Fixture answer"
                content, kind = PCM, "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("PROMETHEE_OPENAI_API_KEY", "explicit-local-test-placeholder")
    common = {
        "generation": "fixture-id",
        "base_url": f"http://127.0.0.1:{server.server_port}/v1",
        "timeout": 5,
        "model": "fixture-only",
    }
    try:
        for operation, payload in [
            ("transcribe", {"pcm": base64.b64encode(PCM).decode()}),
            ("speak", {"text": "Fixture answer", "voice": "fixture"}),
        ]:
            worker = WorkerProcess(
                [sys.executable, "-m", "promethee.voice_worker"],
                {**common, "operation": operation, **payload},
            )
            try:
                deadline = time.monotonic() + 10
                result = None
                while result is None and time.monotonic() < deadline:
                    result = worker.poll()
                    time.sleep(0.02)
                assert result["type"] == "result"
                assert result["generation"] == "fixture-id"
                if operation == "transcribe":
                    assert result["text"] == "Fixture transcript"
                else:
                    assert decode_pcm(result["pcm"], 480000) == PCM
            finally:
                worker.close()
        worker = WorkerProcess(
            [sys.executable, "-m", "promethee.voice_worker"],
            {
                **common,
                "base_url": common["base_url"] + "/denied",
                "operation": "speak",
                "text": "Fixture answer",
                "voice": "fixture",
            },
        )
        try:
            deadline = time.monotonic() + 10
            result = None
            while result is None and time.monotonic() < deadline:
                result = worker.poll()
                time.sleep(0.02)
            assert result == {"type": "error", "code": "audio_provider_failure"}
        finally:
            worker.close()
        assert len(requests) == 3  # No implicit retry, including on a provider refusal.
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
