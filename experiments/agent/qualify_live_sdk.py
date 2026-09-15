"""Exercise OpenAI 3.14.0 Live transport against a local WebSocket fixture.

No OpenAI account, model inference, Hermes call, microphone or speaker is used.
The fixture verifies wire conventions and disconnect behavior, not server-side
acceptance of a configuration or voice quality.
"""

import argparse
import asyncio
import base64
import json
import shutil
from importlib.metadata import version
from pathlib import Path

from openai import AsyncOpenAI
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosedError


async def qualify(output):
    assert version("openai") == "3.14.0"
    assert version("websockets") == "15.0.1"
    pcm = b"\0\0" * 480
    encoded = base64.b64encode(pcm).decode()
    report = {
        "openai": version("openai"),
        "websockets": version("websockets"),
        "provider": "local-fixture",
        "model_inference": False,
        "cases": [],
    }
    for mode in ("exchange", "rejected", "disconnected"):
        case = {"mode": mode, "connections": 0, "sent": [], "received": []}
        report["cases"].append(case)
        server_done = asyncio.get_running_loop().create_future()

        async def handler(socket, case=case, mode=mode, server_done=server_done):
            try:
                case["connections"] += 1
                assert socket.request.path == "/v1/live/sessions"
                start = json.loads(await socket.recv())
                case["sent"].append(start)
                assert start == {
                    "type": "session.start",
                    "event_id": "start-01",
                    "session": {
                        "model": "gpt-live-1",
                        "delegation": {"type": "client"},
                        "store": False,
                        "audio": {"format": {"type": "audio/pcm", "rate": 24000}},
                    },
                }
                if mode == "disconnected":
                    await socket.close(code=1011, reason="Synthetic transport failure")
                    return
                if mode == "rejected":
                    await socket.send(
                        json.dumps(
                            {
                                "type": "error",
                                "event_id": "error-01",
                                "error": {
                                    "type": "invalid_request_error",
                                    "code": "fixture_rejection",
                                    "message": "Synthetic rejection",
                                    "client_event_id": "start-01",
                                },
                            }
                        )
                    )
                    return
                await socket.send(
                    json.dumps(
                        {
                            "type": "session.started",
                            "event_id": "started-01",
                            "client_event_id": "start-01",
                            "session": {"id": "fixture-session", "model": "gpt-live-1"},
                        }
                    )
                )
                audio = json.loads(await socket.recv())
                case["sent"].append(audio)
                assert audio == {"type": "session.input_audio.append", "audio": encoded}
                for event in [
                    {
                        "type": "session.input_transcript.delta",
                        "event_id": "input-01",
                        "start_ms": 0,
                        "end_ms": 100,
                        "delta": "Lis ",
                    },
                    {
                        "type": "session.delegation.created",
                        "event_id": "delegation-01",
                        "offset_ms": 90,
                        "delegation": {
                            "type": "delegation",
                            "id": "item_fixture_opaque",
                            "target": "client",
                        },
                    },
                    {
                        "type": "session.input_transcript.delta",
                        "event_id": "input-02",
                        "start_ms": 100,
                        "end_ms": 200,
                        "delta": "le monde.",
                    },
                ]:
                    await socket.send(json.dumps(event))
                result = json.loads(await socket.recv())
                case["sent"].append(result)
                assert result == {
                    "type": "session.commentary.append",
                    "event_id": "result-01",
                    "delegation_id": "item_fixture_opaque",
                    "content": "Synthetic result; no body action.",
                }
                await socket.send(
                    json.dumps(
                        {
                            "type": "session.commentary.appended",
                            "event_id": "ack-01",
                            "client_event_id": "result-01",
                            "offset_ms": 210,
                            "delegation_id": "item_fixture_opaque",
                        }
                    )
                )
                await socket.send(
                    json.dumps({"type": "session.output_audio.delta", "delta": encoded})
                )
            except BaseException as exc:
                server_done.set_exception(exc)
            finally:
                if not server_done.done():
                    server_done.set_result(None)

        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            # Explicit dummy auth sent only to loopback; no ambient credentials.
            async with AsyncOpenAI(
                api_key="local-fixture-only",
                base_url=f"http://127.0.0.1:{port}/v1",
                websocket_base_url=f"ws://127.0.0.1:{port}/v1",
                max_retries=0,
            ) as client:
                async with client.live.connect(max_retries=0) as connection:
                    await connection.session.start(
                        event_id="start-01",
                        session={
                            "model": "gpt-live-1",
                            "delegation": {"type": "client"},
                            "store": False,
                            "audio": {"format": {"type": "audio/pcm", "rate": 24000}},
                        },
                    )
                    if mode == "disconnected":
                        try:
                            await connection.recv()
                        except ConnectionClosedError:
                            case["disconnect_reported"] = True
                        else:
                            raise AssertionError("Transport failure was not reported.")
                    else:
                        first = await connection.recv()
                        case["received"].append(first.model_dump(exclude_unset=True))
                        if mode == "rejected":
                            assert first.type == "error" and first.error.code == "fixture_rejection"
                        else:
                            assert first.type == "session.started"
                            await connection.session.input_audio.append(audio=encoded)
                            events = [await connection.recv() for _ in range(3)]
                            case["received"].extend(
                                e.model_dump(exclude_unset=True) for e in events
                            )
                            assert events[1].delegation.id == "item_fixture_opaque"
                            assert not hasattr(events[1].delegation, "text")
                            assert events[0].delta + events[2].delta == "Lis le monde."
                            await connection.session.commentary.append(
                                event_id="result-01",
                                delegation_id=events[1].delegation.id,
                                content="Synthetic result; no body action.",
                            )
                            ack, audio = await connection.recv(), await connection.recv()
                            case["received"].extend(
                                e.model_dump(exclude_unset=True) for e in (ack, audio)
                            )
                            assert ack.client_event_id == "result-01"
                            assert base64.b64decode(audio.delta, validate=True) == pcm
                            case["audio_bytes_received"] = len(pcm)
                            case["playback_verified"] = False
                await server_done
        assert case["connections"] == 1
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(
            json.dumps({"case": mode, "connections": case["connections"], "passed": True}),
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.mkdir(exist_ok=False)
    shutil.copyfile(__file__, output / "qualification-source.py")
    asyncio.run(asyncio.wait_for(qualify(output), timeout=30))
