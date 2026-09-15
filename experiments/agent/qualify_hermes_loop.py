"""Exercise native Hermes against a loopback-only deterministic provider fixture.

This verifies transport and history, not reasoning quality or access to Astra.
Keep the fresh output profile and all of its data out of personal agent memory.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from promethee.conversation import ConversationStore
from promethee.execution import ExecutionService
from promethee.runtime import Runtime
from promethee.world import ActionError

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--hermes-python", type=Path, required=True)
parser.add_argument("--hermes-root", type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
output = args.output.resolve()
output.mkdir(exist_ok=False)
shutil.copyfile(__file__, output / "qualification-source.py")
for source in (
    "hermes_worker.py",
    "hermes_adapter.py",
    "mcp_server.py",
    "execution.py",
    "conversation.py",
):
    shutil.copyfile(root / "src/promethee" / source, output / source)
service = ExecutionService(Runtime(output / "world.sqlite3", data_origin="session"))
conversation = ConversationStore(service)
calls = []
auxiliary = []


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if "messages" not in request:
            auxiliary.append({"path": self.path, "keys": list(request)})
            self.send_error(404, "Auxiliary endpoint not implemented by the fixture")
            return
        calls.append(request)
        if index == 3:
            body = json.dumps(
                {
                    "error": {
                        "message": "Diagnostic provider unavailable",
                        "type": "invalid_api_key",
                        "code": "invalid_api_key",
                    }
                }
            ).encode()
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        last = request["messages"][-1]
        message = (
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-world",
                        "type": "function",
                        "function": {"name": "mcp__promethee__read_world", "arguments": "{}"},
                    }
                ],
            }
            if last["role"] != "tool"
            else {"role": "assistant", "content": "Diagnostic fixture: world read."}
        )
        if index == 2 and last["role"] != "tool":
            # A new trusted user turn arrives while the old provider is answering.
            # Even a freshly supplied world revision must not revive the old tools.
            service.begin_turn(timeout=90)
            message["tool_calls"][0]["function"] = {
                "name": "mcp__promethee__submit_action",
                "arguments": json.dumps(
                    {
                        "request_id": "late-proposal",
                        "expected_revision": service.get_world()["revision"],
                        "action": {"kind": "move", "args": {"position": [0.2, 0.3]}},
                    }
                ),
            }
        finish = "tool_calls" if "tool_calls" in message else "stop"
        common = {
            "id": "fixture-completion",
            "created": int(time.time()),
            "model": "diagnostic-fixture",
        }
        if request.get("stream"):
            delta = dict(message)
            if "tool_calls" in delta:
                delta["tool_calls"] = [{"index": 0, **delta["tool_calls"][0]}]
            data = ""
            for value, reason in [(delta, None), ({}, finish)]:
                chunk = {
                    **common,
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": value, "finish_reason": reason}],
                }
                data += "data: " + json.dumps(chunk) + "\n\n"
            body = (data + "data: [DONE]\n\n").encode()
            content_type = "text/event-stream"
        else:
            body = json.dumps(
                {
                    **common,
                    "object": "chat.completion",
                    "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
            ).encode()
            content_type = "application/json"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
results = []
try:
    for index in range(4):
        user_message = f"Developer diagnostic {index}: read world."
        opened = conversation.begin(user_message, timeout=90)
        turn = opened["turn_id"]
        if index == 1:
            assert opened["history"] == results[0]["messages"]
        if index == 3:
            assert opened["history"] == [
                *results[1]["messages"],
                {"role": "user", "content": "Developer diagnostic 2: read world."},
            ]
        profile = output / f"profile-{index}"
        profile.mkdir()
        config = {
            "tools": {"tool_search": {"enabled": "off"}},
            "mcp_servers": {
                "promethee": {
                    "command": sys.executable,
                    "args": [
                        "-m",
                        "promethee.mcp_server",
                        "--data-dir",
                        str(output),
                        "--turn-id",
                        turn,
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
        (profile / "config.yaml").write_text(json.dumps(config))
        request = {
            "turn_id": turn,
            "message": user_message,
            "history": opened["history"],
            "model": "diagnostic-fixture",
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
            "api_mode": "chat_completions",
            "session_id": opened["session_id"],
        }
        env = {**os.environ, "PROMETHEE_OPENAI_API_KEY": "diagnostic-placeholder"}
        started = time.monotonic()
        proc = subprocess.run(
            [
                str(args.hermes_python.resolve()),
                "-X",
                "utf8",
                str(root / "src/promethee/hermes_worker.py"),
                "--profile",
                str(profile),
                "--hermes-root",
                str(args.hermes_root.resolve()),
            ],
            input=json.dumps(request) + "\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
            env=env,
        )
        (output / f"worker-{index}.log").write_text(proc.stderr, encoding="utf-8")
        result = json.loads(proc.stdout)
        results.append({"elapsed_seconds": time.monotonic() - started, **result})
        print(json.dumps({k: v for k, v in results[-1].items() if k != "messages"}), flush=True)
        assert result["type"] == "result"
        if index == 3:
            assert result["failed"]
            conversation.abort(turn)
            results[-1]["delivered"] = False
            continue
        assert not result["failed"]
        assert result["text"] == "Diagnostic fixture: world read."
        if index < 2:
            conversation.finish(turn, result)
            results[-1]["delivered"] = True
        else:
            try:
                conversation.finish(turn, result)
            except ActionError:
                conversation.abort(turn, status="interrupted")
                results[-1]["delivered"] = False
            else:
                raise AssertionError("A superseded reply was accepted for delivery.")
            assert any(
                m.get("role") == "tool" and "obsolete" in m.get("content", "")
                for m in result["messages"]
            )
    assert len(calls) == 7, len(calls)
    assert any(
        m.get("content") == "Developer diagnostic 0: read world." for m in calls[2]["messages"]
    )
    assert service.events() == []
finally:
    server.shutdown()
    server.server_close()
    (output / "report.json").write_text(
        json.dumps(
            {
                "purpose": "developer qualification only",
                "provider": "local deterministic fixture, not Astra",
                "calls": len(calls),
                "auxiliary": auxiliary,
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
