"""Local Live wire fixture for the full parent/SDK/Hermes session diagnostic."""

import argparse
import asyncio
import base64
import json
import time
from pathlib import Path

from websockets.asyncio.server import serve


async def main(output):
    done = asyncio.get_running_loop().create_future()
    report = {"connections": 0, "audio_chunks": 0, "results": [], "audio_times": []}

    async def handler(socket):
        try:
            report["connections"] += 1
            assert socket.request.headers["Authorization"] == "Bearer local-fixture-only"
            assert socket.request.path == "/v1/live/sessions"
            start = json.loads(await socket.recv())
            assert start["type"] == "session.start"
            await socket.send(
                json.dumps(
                    {
                        "type": "session.started",
                        "event_id": "started-fixture",
                        "session": {"id": "live-session-fixture", "model": "gpt-live-1"},
                    }
                )
            )
            started = time.monotonic()
            while True:
                event = json.loads(await socket.recv())
                if event["type"] == "session.input_audio.append":
                    assert len(base64.b64decode(event["audio"], validate=True)) == 960
                    report["audio_chunks"] += 1
                    report["audio_times"].append(time.monotonic() - started)
                    if report["audio_chunks"] == 1:
                        for fragment in [
                            {
                                "type": "session.input_transcript.delta",
                                "event_id": "input-1",
                                "start_ms": 0,
                                "end_ms": 50,
                                "delta": "Lis le monde et ",
                            },
                            {
                                "type": "session.delegation.created",
                                "event_id": "delegate-1",
                                "offset_ms": 40,
                                "delegation": {
                                    "id": "item_loop_opaque",
                                    "type": "delegation",
                                    "target": "client",
                                },
                            },
                            {
                                "type": "session.input_transcript.delta",
                                "event_id": "input-2",
                                "start_ms": 50,
                                "end_ms": 100,
                                "delta": "indique les objets présents, sans agir.",
                            },
                        ]:
                            await socket.send(json.dumps(fragment))
                elif event["type"] == "session.commentary.append":
                    assert event["delegation_id"] == "item_loop_opaque"
                    report["results"].append(
                        {"elapsed_seconds": time.monotonic() - started, "event": event}
                    )
                    await socket.send(
                        json.dumps(
                            {
                                "type": "session.commentary.appended",
                                "event_id": "ack-1",
                                "client_event_id": event["event_id"],
                                "offset_ms": 100,
                                "delegation_id": "item_loop_opaque",
                            }
                        )
                    )
                    await socket.send(
                        json.dumps(
                            {
                                "type": "session.output_audio.delta",
                                "delta": base64.b64encode(b"\0" * 960).decode(),
                            }
                        )
                    )
                elif event["type"] == "session.close":
                    await socket.send(
                        json.dumps(
                            {
                                "type": "session.closed",
                                "event_id": "closed-1",
                                "reason": "close_requested",
                                "session": {"id": "live-session-fixture"},
                                "usage": {"seconds": report["audio_chunks"] * 0.02},
                            }
                        )
                    )
                    await socket.wait_closed()
                    assert len(report["results"]) == 1
                    done.set_result(None)
                    return
                else:
                    raise AssertionError("Unexpected client event.")
        except BaseException as exc:
            if not done.done():
                done.set_exception(exc)

    async with serve(handler, "127.0.0.1", 0) as server:
        print(
            json.dumps({"type": "fixture.ready", "port": server.sockets[0].getsockname()[1]}),
            flush=True,
        )
        await asyncio.wait_for(done, 100)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "type": "fixture.completed",
                "connections": report["connections"],
                "results": len(report["results"]),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    asyncio.run(main(parser.parse_args().report))
