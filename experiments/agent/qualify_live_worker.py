"""Run the real isolated SDK worker against local fixtures, without audio devices."""

import argparse
import asyncio
import base64
import json
import os
import shutil
import sys
import time
from pathlib import Path

from websockets.asyncio.server import serve

WORKER = Path(__file__).resolve().parents[2] / "src/promethee/live_worker.py"


async def qualify(output):
    report = {"provider": "local-fixture", "model_inference": False, "cases": []}
    for mode in ("exchange", "invalid", "disconnected", "missing_usage", "silent"):
        case = {"mode": mode, "connections": 0, "sent": [], "received": []}
        done = asyncio.get_running_loop().create_future()

        async def handler(socket, mode=mode, case=case, done=done):
            try:
                case["connections"] += 1
                assert socket.request.path == "/v1/live/sessions"
                assert socket.request.headers["Authorization"] == "Bearer local-fixture-only"
                start = json.loads(await socket.recv())
                case["sent"].append(start)
                assert start["type"] == "session.start"
                assert start["session"]["delegation"] == {"type": "client"}
                assert start["session"]["store"] is False
                await socket.send(
                    json.dumps(
                        {
                            "type": "session.started",
                            "event_id": "started-1",
                            "session": {"id": "fixture-session", "model": "gpt-live-1"},
                        }
                    )
                )
                if mode == "exchange":
                    audio = json.loads(await socket.recv())
                    case["sent"].append(audio)
                    assert audio == {"type": "session.input_audio.append", "audio": "AAA="}
                    await socket.send(
                        json.dumps(
                            {
                                "type": "session.delegation.created",
                                "event_id": "delegation-1",
                                "offset_ms": 0,
                                "delegation": {
                                    "id": "item_Opaque-17",
                                    "type": "delegation",
                                    "target": "client",
                                },
                            }
                        )
                    )
                    reply = json.loads(await socket.recv())
                    case["sent"].append(reply)
                    assert reply["delegation_id"] == "item_Opaque-17"
                    await socket.send(
                        json.dumps({"type": "session.output_audio.delta", "delta": "AAA="})
                    )
                close = json.loads(await socket.recv())
                case["sent"].append(close)
                assert close["type"] == "session.close"
                if mode == "disconnected":
                    await socket.close(code=1011, reason="Private fixture text")
                elif mode == "silent":
                    await socket.wait_closed()
                else:
                    final = {
                        "type": "session.closed",
                        "event_id": "closed-1",
                        "reason": "close_requested",
                        "session": {"id": "fixture-session"},
                        "usage": {"seconds": 0.02},
                    }
                    if mode == "missing_usage":
                        del final["usage"]
                    await socket.send(json.dumps(final))
                    await socket.wait_closed()
            except BaseException as exc:
                done.set_exception(exc)
            finally:
                if not done.done():
                    done.set_result(None)

        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            env = {**os.environ, "PROMETHEE_OPENAI_API_KEY": "must-not-leave-the-process"}
            started = time.monotonic()
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-X",
                "utf8",
                str(WORKER),
                "--model",
                "gpt-live-1",
                "--voice",
                "marin",
                "--max-seconds",
                "30",
                "--test-url",
                f"ws://127.0.0.1:{port}/v1",
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            async def read_event(process=process, case=case):
                event = json.loads(await asyncio.wait_for(process.stdout.readline(), 20))
                case["received"].append(event)
                return event

            async def write_event(event, process=process):
                process.stdin.write(json.dumps(event).encode() + b"\n")
                await process.stdin.drain()

            try:
                assert (await read_event())["type"] == "session.started"
                if mode == "exchange":
                    await write_event({"type": "session.input_audio.append", "audio": "AAA="})
                    delegation = await read_event()
                    await write_event(
                        {
                            "type": "session.commentary.append",
                            "delegation_id": delegation["delegation"]["id"],
                            "content": "Synthetic result; no body action.",
                        }
                    )
                    audio = await read_event()
                    assert base64.b64decode(audio["delta"]) == b"\0\0"
                elif mode == "invalid":
                    await write_event({"type": []})
                process.stdin.close()
                stdout, stderr = await asyncio.wait_for(process.communicate(), 20)
                case["received"].extend(json.loads(line) for line in stdout.splitlines())
                assert not stderr, stderr.decode(errors="replace")
                assert b"must-not-leave-the-process" not in stdout + stderr
                assert b"Private fixture text" not in stdout + stderr
                assert process.returncode == (0 if mode == "exchange" else 1)
                assert case["connections"] == 1
                if mode == "silent":
                    assert case["received"][-1]["code"] == "live_finalization_timeout"
                if mode in {"missing_usage", "disconnected", "silent"}:
                    assert not any(e["type"] == "session.closed" for e in case["received"])
                await asyncio.wait_for(done, 5)
                case.update(passed=True, elapsed_seconds=time.monotonic() - started)
                report["cases"].append(case)
                print(json.dumps({"case": mode, "passed": True}), flush=True)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.mkdir(exist_ok=False)
    shutil.copyfile(__file__, output / "qualification-source.py")
    shutil.copyfile(WORKER, output / "worker-source.py")
    asyncio.run(asyncio.wait_for(qualify(output), 60))
