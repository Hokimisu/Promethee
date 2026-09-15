"""Real Hermes/process host against a loopback fixture, never Astra or personal memory."""

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from promethee.chat import TextHost, WorkerProcess, exclusive_host, prepare_profile
from promethee.conversation import ConversationStore
from promethee.execution import ExecutionService
from promethee.migrations import read_world
from promethee.runtime import Runtime, encode

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--hermes-python", type=Path, required=True)
parser.add_argument("--hermes-root", type=Path, required=True)
parser.add_argument(
    "--memory", action="store_true", help="Exercise the four sourced memory tools too."
)
parser.add_argument(
    "--voice", action="store_true", help="Exercise chained audio with synthetic PCM, no devices."
)
args = parser.parse_args()
output = args.output.resolve()
output.mkdir(exist_ok=False)
root = Path(__file__).resolve().parents[2]
shutil.copyfile(__file__, output / "qualification-source.py")
for name in (
    "chat.py",
    "conversation.py",
    "hermes_worker.py",
    "hermes_adapter.py",
    "windows_job.py",
    "memory.py",
    "mcp_server.py",
    "migrations.py",
    "voice.py",
    "voice_worker.py",
):
    shutil.copyfile(root / "src/promethee" / name, output / name)
(output / "purpose.json").write_text(
    json.dumps(
        {
            "purpose": "developer qualification only",
            "provider": "local deterministic fixture, not Astra",
        }
    )
)
calls, results, workers = [], [], []
slow_started, release_slow = threading.Event(), threading.Event()


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        if args.voice and self.path in {"/v1/audio/transcriptions", "/v1/audio/speech"}:
            if self.path.endswith("transcriptions"):
                assert b"RIFF" in raw and b"recording.wav" in raw
                body, content_type = b'{"text":"Read the world"}', "application/json"
            else:
                request = json.loads(raw)
                assert request["input"] == "Diagnostic host: world read."
                assert request["response_format"] == "pcm"
                body, content_type = b"\x01\x00" * 2400, "application/octet-stream"
            calls.append({"audio": self.path, "at": time.monotonic()})
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        request = json.loads(raw)
        if "messages" not in request:
            self.send_error(404)
            return
        user = [m for m in request["messages"] if m["role"] == "user"][-1]["content"]
        calls.append({"message": user, "at": time.monotonic()})
        # The native adapter merges unanswered user messages in its wire copy.
        # These exact diagnostic labels select fixture behavior, never agent policy.
        current = user.rsplit("\n\n", 1)[-1]
        if current == "Wait for correction" or current == "Exceed deadline":
            slow_started.set()
            release_slow.wait(timeout=30)
        if current == "Provider failure":
            self.send_error(401, "Diagnostic provider unavailable")
            return
        message = {"role": "assistant", "content": "Diagnostic host: world read."}
        if request["messages"][-1]["role"] != "tool":
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call-world",
                        "type": "function",
                        "function": {"name": "mcp__promethee__read_world", "arguments": "{}"},
                    }
                ],
            }
        elif args.memory and current == "Remember qualification":
            last_call = request["messages"][-1].get("tool_call_id")
            operation = None
            if last_call == "call-world":
                operation = (
                    "call-memory-write",
                    "write_memory_note",
                    {
                        "note_id": "qualification-note",
                        "kind": "proposal",
                        "title": "Qualification",
                        "text": "This note belongs only to developer qualification.",
                        "sources": ["user:" + service.get_world()["conversation"]["turn_id"]],
                    },
                )
            elif last_call == "call-memory-write":
                operation = ("call-memory-search", "search_memory", {"query": "qualification"})
            if operation:
                call_id, name, parameters = operation
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": "mcp__promethee__" + name,
                                "arguments": json.dumps(parameters),
                            },
                        }
                    ],
                }
        finish = "tool_calls" if "tool_calls" in message else "stop"
        chunks = []
        for delta, reason in [(message, None), ({}, finish)]:
            chunks.append(
                "data: "
                + json.dumps(
                    {
                        "id": "host-fixture",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": "diagnostic-fixture",
                        "choices": [{"index": 0, "delta": delta, "finish_reason": reason}],
                    }
                )
                + "\n\n"
            )
        body = ("".join(chunks) + "data: [DONE]\n\n").encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # A corrected/deadline-exceeded worker deliberately closed its connection.


def wait_for(callback, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = callback()
        if value:
            return value
        time.sleep(0.02)
    raise TimeoutError("Qualification condition was not reached.")


server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
threading.Thread(target=server.serve_forever, daemon=True).start()
service = ExecutionService(
    Runtime(
        output / "world.sqlite3",
        data_origin="session",
        session_kind="interactive" if args.memory else "qualification",
    )
)
vault = None
if args.memory:
    from promethee.memory import MemoryStore, initialize_vault

    vault = initialize_vault(service.runtime, output / "vault")
prior_key = os.environ.get("PROMETHEE_OPENAI_API_KEY")
os.environ["PROMETHEE_OPENAI_API_KEY"] = "diagnostic-placeholder"
base_url = f"http://127.0.0.1:{server.server_port}/v1"


def factory(request):
    profile = output / "profiles" / request["turn_id"]
    prepare_profile(profile, output, request["turn_id"], vault=vault)
    process = WorkerProcess(
        [
            str(args.hermes_python.resolve()),
            "-X",
            "utf8",
            str(root / "src/promethee/hermes_worker.py"),
            "--hermes-root",
            str(args.hermes_root.resolve()),
            "--profile",
            str(profile),
        ],
        request,
    )
    workers.append(process)
    original_poll = process.poll

    def recorded_poll():
        result = original_poll()
        if result is not None:
            (profile / "worker-result.json").write_text(json.dumps(result, indent=2))
        return result

    process.poll = recorded_poll
    return process


try:
    with exclusive_host(output):
        host = TextHost(
            ConversationStore(service),
            factory,
            model="diagnostic-fixture",
            base_url=base_url,
            api_mode="chat_completions",
            timeout=40,
        )
        try:
            started = time.monotonic()
            host.start("Read the world")
            result = wait_for(host.poll)
            assert result["status"] == "completed", result
            results.append({"case": "read", "elapsed": time.monotonic() - started, **result})
            print(json.dumps(results[-1]), flush=True)
            if args.voice:
                from promethee.voice import VoiceHost

                class SyntheticDevice:
                    active, error = False, None

                    def listen(self):
                        self.active = True

                    def stop(self):
                        self.active = False

                    def finish_recording(self):
                        self.stop()
                        return b"\x01\x00" * 2400

                    def play(self, pcm):
                        assert pcm == b"\x01\x00" * 2400
                        self.active = True

                voice_host = VoiceHost(
                    host,
                    lambda request: WorkerProcess(
                        [sys.executable, "-m", "promethee.voice_worker"], request
                    ),
                    SyntheticDevice(),
                    transcription_model="diagnostic-fixture",
                    speech_model="diagnostic-fixture",
                    voice="fixture",
                    base_url=base_url,
                )
                try:
                    voice_host.listen()
                    voice_host.finish_listening()
                    stages = []
                    while voice_host.state != "speaking":
                        result = wait_for(voice_host.poll)
                        stages.append(result)
                        assert result["status"] != "failed", result
                    interrupted = voice_host.interrupt()
                    results.append(
                        {
                            "case": "chained-voice-synthetic-device",
                            "stages": stages,
                            "interruption": interrupted,
                            "provider_cost": 0,
                            "actual_microphone_or_speakers": False,
                        }
                    )
                    print(json.dumps(results[-1]), flush=True)
                finally:
                    voice_host.interrupt()
            if args.memory:
                host.start("Remember qualification")
                result = wait_for(host.poll)
                assert result["status"] == "completed", result
                notes = MemoryStore(service, vault).search("qualification")["notes"]
                assert [note["note_id"] for note in notes] == ["qualification-note"]
                results.append({"case": "sourced-memory", **result})
                print(json.dumps(results[-1]), flush=True)

            host.start("Wait for correction")
            wait_for(slow_started.is_set)
            old = workers[-1]
            started = time.monotonic()
            host.start("Correction: read the current world")
            stopped = time.monotonic() - started
            assert old.process.poll() is not None
            release_slow.set()
            result = wait_for(host.poll)
            assert result["status"] == "completed", result
            results.append({"case": "correction", "stop_seconds": stopped, **result})
            print(json.dumps(results[-1]), flush=True)

            slow_started.clear()
            release_slow.clear()
            host.timeout = 15
            started = time.monotonic()
            host.start("Exceed deadline")
            wait_for(slow_started.is_set)
            result = wait_for(host.poll)
            assert result.get("code") == "deadline_exceeded", result
            assert workers[-1].process.poll() is not None
            results.append({"case": "deadline", "elapsed": time.monotonic() - started, **result})
            print(json.dumps(results[-1]), flush=True)
            release_slow.set()

            host.timeout = 40
            host.start("Provider failure")
            result = wait_for(host.poll)
            assert result["status"] == "failed", result
            results.append({"case": "provider-failure", **result})
            print(json.dumps(results[-1]), flush=True)
        finally:
            host.close()
    # Exercise the public CLI after a host restart, against the same persisted history.
    proc = subprocess.Popen(
        [
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "promethee.cli",
            "--data-dir",
            str(output),
            "chat",
            "--hermes-python",
            str(args.hermes_python.resolve()),
            "--hermes-root",
            str(args.hermes_root.resolve()),
            "--model",
            "diagnostic-fixture",
            "--api-mode",
            "chat_completions",
            "--base-url",
            base_url,
        ]
        + (["--vault", str(vault)] if vault is not None else []),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        creationflags=(subprocess.CREATE_NO_WINDOW | 4) if os.name == "nt" else 0,
        start_new_session=os.name != "nt",
    )
    job = None
    if os.name == "nt":
        from promethee.windows_job import WindowsJob

        job = WindowsJob(proc)
        job.resume(proc.pid)
    lines = queue.Queue()

    def read_lines():
        for line in proc.stdout:
            lines.put(line)
        lines.put("")

    threading.Thread(target=read_lines, daemon=True).start()
    try:
        assert "un message par ligne" in lines.get(timeout=10)
        proc.stdin.write("CLI: read the world\n")
        proc.stdin.flush()
        result = json.loads(lines.get(timeout=45))
        assert result["status"] == "completed", result
        proc.stdin.write("/quit\n")
        proc.stdin.flush()
        proc.wait(timeout=10)
        assert proc.returncode == 0, proc.stderr.read()
        results.append({"case": "cli-restart", **result})
        print(json.dumps(results[-1]), flush=True)
    finally:
        if job:
            job.close()
        elif os.name != "nt":
            import signal

            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.wait(timeout=5)
        proc.stdin.close()
        proc.stdout.close()
        proc.stderr.close()
    assert service.events() == []
    assert all(worker.process.poll() is not None for worker in workers)
finally:
    release_slow.set()
    server.shutdown()
    server.server_close()
    if prior_key is None:
        os.environ.pop("PROMETHEE_OPENAI_API_KEY", None)
    else:
        os.environ["PROMETHEE_OPENAI_API_KEY"] = prior_key
    if args.memory:
        # Irreversible downgrade of this isolated test artifact; never promote it
        # into personal memory merely because it exercised the interactive contract.
        with service.runtime.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            world = read_world(conn)
            world.update(session_kind="qualification", conversation=None)
            world["revision"] += 1
            conn.execute("UPDATE world SET data=? WHERE id=1", (encode(world),))
    (output / "report.json").write_text(json.dumps({"results": results, "calls": calls}, indent=2))
