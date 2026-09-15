"""Bounded JSON-lines Live transport for a separate OpenAI 3.14.0 environment.

No microphone, playback device, body controller, or agent runs in this process.
The parent drains stdout and owns audio pacing, conversation and decisions.
"""

import argparse
import asyncio
import base64
import json
import math
import os
import queue
import sys
import threading
import time
from importlib.metadata import version
from urllib.parse import urlsplit

LIMIT = 1_048_576


def command(value):
    if not isinstance(value, dict):
        raise ValueError("Expected an event object.")
    kind = value.get("type")
    if not isinstance(kind, str):
        raise ValueError("Expected an event type.")
    if kind in {"session.close", "session.input_audio.mute", "session.input_audio.unmute"}:
        keys = {"type"}
    elif kind == "session.input_audio.append":
        keys = {"type", "audio"}
        audio = value.get("audio")
        if not isinstance(audio, str) or len(audio) > 64000:
            raise ValueError("Audio chunk exceeds one second.")
        pcm = base64.b64decode(audio, validate=True)
        if not pcm or len(pcm) % 2 or len(pcm) > 48000:
            raise ValueError("Expected PCM16 mono at 24 kHz.")
    elif kind in {
        "session.commentary.append",
        "session.thinking.append",
        "session.instructions.append",
    }:
        keys = {"type", "delegation_id", "content"}
        content, delegation = value.get("content"), value.get("delegation_id")
        if not isinstance(content, str) or not content.strip() or len(content.encode()) > 4000:
            raise ValueError("Context must be nonempty and bounded.")
        if delegation is not None and (
            not isinstance(delegation, str) or not 1 <= len(delegation) <= 200
        ):
            raise ValueError("Invalid delegation identifier.")
    else:
        raise ValueError("Unsupported Live client event.")
    if "event_id" in value:
        identifier = value["event_id"]
        if not isinstance(identifier, str) or not 1 <= len(identifier) <= 200:
            raise ValueError("Invalid event identifier.")
        keys.add("event_id")
    if set(value) != keys:
        raise ValueError("Unexpected event fields.")
    return value


def emit(value):
    line = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if len(line.encode()) > LIMIT:
        raise ValueError("Provider event exceeds the transport limit.")
    print(line, flush=True)


def final_usage(event):
    """Unchecked SDK construction is not proof of a final accounting receipt."""
    usage = event.get("usage")
    seconds = usage.get("seconds") if isinstance(usage, dict) else None
    session = event.get("session")
    if (
        not isinstance(session, dict)
        or not isinstance(session.get("id"), str)
        or not session["id"]
        or event.get("reason") not in {"close_requested", "expired"}
        or type(seconds) not in (int, float)
        or not math.isfinite(seconds)
        or seconds < 0
    ):
        raise ValueError("Missing or unsuccessful final accounting receipt.")


async def run(args):
    from openai import AsyncOpenAI

    incoming = queue.Queue(maxsize=8)

    def read():
        while True:
            line = sys.stdin.buffer.readline(LIMIT + 1)
            if not line:
                incoming.put(None)
                return
            if len(line) > LIMIT or not line.endswith(b"\n"):
                incoming.put({"invalid": True})
                return
            try:
                incoming.put(command(json.loads(line)))
            except (ValueError, UnicodeError):
                incoming.put({"invalid": True})
                return

    settings = {"api_key": os.environ.get("PROMETHEE_OPENAI_API_KEY"), "max_retries": 0}
    if args.test_url:
        url = urlsplit(args.test_url)
        if (
            url.scheme != "ws"
            or url.hostname != "127.0.0.1"
            or not url.port
            or url.path != "/v1"
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("The test transport must use an explicit loopback port and /v1.")
        settings.update(
            api_key="local-fixture-only",
            websocket_base_url=args.test_url,
            base_url=f"http://127.0.0.1:{url.port}/v1",
        )
    if not settings["api_key"]:
        emit({"type": "transport.error", "code": "missing_audio_key"})
        return 2
    async with AsyncOpenAI(**settings) as client:
        async with client.live.connect(
            max_retries=0,
            websocket_connection_options={"open_timeout": 15, "close_timeout": 2},
        ) as connection:
            await connection.session.start(
                session={
                    "model": args.model,
                    "delegation": {"type": "client"},
                    "store": False,
                    "audio": {
                        "format": {"type": "audio/pcm", "rate": 24000},
                        "output": {"voice": args.voice},
                    },
                },
                event_id="promethee-start",
            )
            first = await asyncio.wait_for(connection.recv(), timeout=15)
            if first.type != "session.started":
                emit({"type": "transport.error", "code": "live_start_rejected"})
                return 1
            emit(first.model_dump(exclude_unset=True))
            threading.Thread(target=read, daemon=True).start()
            deadline, closing, invalid = time.monotonic() + args.max_seconds, None, False
            pending = asyncio.create_task(connection.recv())
            try:
                while True:
                    if closing is None:
                        try:
                            event = incoming.get_nowait()
                        except queue.Empty:
                            event = False
                        expired = time.monotonic() >= deadline
                        if event is None or expired or (event and event.get("invalid")):
                            invalid = bool(event and event.get("invalid"))
                            await connection.session.close()
                            closing = time.monotonic() + 15
                        elif event:
                            await connection.send(event)
                            if event["type"] == "session.close":
                                closing = time.monotonic() + 15
                    if closing is not None and time.monotonic() >= closing:
                        emit({"type": "transport.error", "code": "live_finalization_timeout"})
                        return 1
                    # Input arrives at 50 Hz; a 20 ms wait per command cannot
                    # keep up once scheduling overhead or context events accrue.
                    done, _ = await asyncio.wait({pending}, timeout=0.005)
                    if not done:
                        continue
                    received = pending.result()
                    if received.type == "error":
                        # Provider messages can echo private input; emit a fixed failure code.
                        emit({"type": "transport.error", "code": "live_provider_error"})
                        if closing is None:
                            await connection.session.close()
                            closing = time.monotonic() + 15
                        invalid = True
                    else:
                        payload = received.model_dump(exclude_unset=True)
                        if received.type == "session.closed":
                            final_usage(payload)
                        emit(payload)
                    if received.type == "session.closed":
                        if invalid:
                            emit({"type": "transport.error", "code": "live_session_failed"})
                        return 1 if invalid else 0
                    pending = asyncio.create_task(connection.recv())
            finally:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--voice", required=True)
    parser.add_argument("--max-seconds", type=int, required=True)
    parser.add_argument(
        "--test-url", help="Loopback fixture only; uses dummy auth, never the account key."
    )
    args = parser.parse_args()
    try:
        if not 1 <= args.max_seconds <= 900:
            raise ValueError("Choose a bounded session duration.")
        if version("openai") != "3.14.0" or version("websockets") != "15.0.1":
            raise ValueError("Use the qualified Live environment.")
        return asyncio.run(run(args))
    except Exception:
        emit({"type": "transport.error", "code": "live_transport_failure"})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
