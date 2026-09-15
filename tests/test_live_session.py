import base64
import collections
import sys
import time

import pytest

from promethee.live_process import LiveProcess
from promethee.live_session import run_session


def until(callback):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = callback()
        if result is not None:
            return result
        time.sleep(0.01)
    raise AssertionError("Worker deadline exceeded.")


def test_real_pipes_preserve_order_and_report_exit_after_queued_events():
    script = (
        "import sys,json\n"
        "for line in sys.stdin:\n"
        " print(json.dumps({'type':'fixture','received':json.loads(line)}),flush=True)\n"
    )
    process = LiveProcess([sys.executable, "-c", script])
    try:
        commands = [{"type": "session.input_audio.mute"}, {"type": "session.input_audio.unmute"}]
        for event in commands:
            process.send(event)
        process.finish()
        assert [until(process.poll)["received"] for _ in commands] == commands
        assert until(process.poll) == {"type": "transport.exited", "returncode": 0}
    finally:
        process.close()
    assert not process.reader.is_alive() and not process.writer.is_alive()


@pytest.mark.parametrize(
    "output", ["private invalid text", "x" * 1_048_577], ids=["invalid", "oversized"]
)
def test_bad_worker_output_fails_without_echoing_private_content(output, tmp_path):
    source = tmp_path / "invalid.txt"
    source.write_text(output, encoding="utf-8")
    process = LiveProcess(
        [
            sys.executable,
            "-c",
            "import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text(),flush=True)",
            str(source),
        ]
    )
    try:
        with pytest.raises(ValueError, match="live_pipe_read_failed"):
            until(process.poll)
    finally:
        process.close()


def test_full_input_pipe_remains_interruptible():
    process = LiveProcess([sys.executable, "-c", "import time; time.sleep(60)"])
    event = {"type": "session.commentary.append", "delegation_id": None, "content": "x" * 4000}
    try:
        started = time.monotonic()
        with pytest.raises(ValueError, match="backpressure"):
            for _ in range(1000):
                process.send(event)
        assert time.monotonic() - started < 2
    finally:
        process.close()
    assert process.process.poll() is not None
    assert not process.reader.is_alive() and not process.writer.is_alive()


class Bridge:
    session = "fixture-session"

    def __init__(self):
        self.started = self.closed = False

    def accept(self, event):
        self.started = True

    def poll(self):
        # Simulate native process startup/cleanup taking much longer than an audio frame.
        time.sleep(0.35)
        return [
            {
                "event": {
                    "type": "session.commentary.append",
                    "delegation_id": "opaque",
                    "content": "Result.",
                }
            }
        ]

    def close(self):
        self.closed = True


class Transport:
    def __init__(self, *, wrong_session=False, no_usage=False):
        self.events = collections.deque(
            [{"type": "session.started", "session": {"id": "fixture-session"}}]
        )
        self.sent = []
        self.wrong_session, self.no_usage = wrong_session, no_usage

    def poll(self):
        return self.events.popleft() if self.events else None

    def send(self, event):
        self.sent.append((time.monotonic(), event))
        if event["type"] == "session.commentary.append":
            receipt = {
                "type": "session.closed",
                "reason": "close_requested",
                "session": {"id": "wrong" if self.wrong_session else "fixture-session"},
                "usage": {"seconds": 0.35},
            }
            if self.no_usage:
                del receipt["usage"]
            self.events.extend(
                [
                    {
                        "type": "session.output_audio.delta",
                        "delta": base64.b64encode(b"\0" * 960).decode(),
                    },
                    receipt,
                    {"type": "transport.exited", "returncode": 0},
                ]
            )

    def finish(self, *, discard=False):
        if discard:
            return
        raise AssertionError("Fixture should complete before the duration limit.")


def test_audio_is_paced_while_hermes_blocks_and_final_usage_is_checked():
    transport, bridge, audio, events = Transport(), Bridge(), bytearray(), []
    result = run_session(
        transport, bridge, lambda frames: b"", audio.extend, events.append, duration=5
    )
    chunks = [
        (at, event) for at, event in transport.sent if event["type"] == "session.input_audio.append"
    ]
    assert len(chunks) >= 10
    assert chunks[-1][0] - chunks[0][0] >= 0.2
    assert all(len(base64.b64decode(event["audio"])) == 960 for _, event in chunks)
    assert result["input_samples"] == len(chunks) * 480
    assert result["output_samples"] == 480
    assert result["usage"] == {"seconds": 0.35}
    assert result["playback_verified"] is False
    assert len(audio) == 960 and bridge.closed
    assert any(event["source"] == "hermes" for event in events)


@pytest.mark.parametrize("options", [{"wrong_session": True}, {"no_usage": True}])
def test_incomplete_or_mismatched_final_usage_is_not_success(options):
    transport = Transport(**options)
    with pytest.raises(ValueError):
        run_session(
            transport,
            Bridge(),
            lambda frames: b"",
            lambda pcm: None,
            lambda event: None,
            duration=5,
        )
    count = len(transport.sent)
    time.sleep(0.05)
    assert len(transport.sent) == count  # Input thread stopped despite validation failure.


@pytest.mark.parametrize("late_result", [False, True])
def test_provider_expiry_keeps_final_receipt_despite_inflight_pipe_writes(late_result):
    script = """
import json,os,time
print(json.dumps({'type':'session.started','session':{'id':'fixture-session'}}),flush=True)
time.sleep(.05)
os.close(0)
time.sleep(.05)
print(json.dumps({'type':'session.closed','reason':'expired',
 'session':{'id':'fixture-session'},'usage':{'seconds':.1}}),flush=True)
"""
    process = LiveProcess([sys.executable, "-c", script])

    class SlowBridge(Bridge):
        def poll(self):
            time.sleep(0.35)
            return (
                [
                    {
                        "event": {
                            "type": "session.commentary.append",
                            "delegation_id": "opaque",
                            "content": "Late result.",
                        }
                    }
                ]
                if late_result
                else []
            )

    bridge = SlowBridge()
    events = []
    try:
        result = run_session(
            process, bridge, lambda frames: b"", lambda pcm: None, events.append, duration=5
        )
        assert result["reason"] == "expired"
        assert result["usage"] == {"seconds": 0.1}
        assert bridge.closed
        if late_result:
            assert [e["delivery"] for e in events if e["source"] == "hermes"] == [
                "not_sent_transport_closed"
            ]
    finally:
        process.close()


@pytest.mark.parametrize(
    "ending",
    [
        "raise SystemExit(7)",
        "print('invalid private trailer',flush=True)",
        "print(json.dumps({'type':'session.output_audio.delta','delta':'AAA='}),flush=True)",
    ],
)
def test_final_receipt_does_not_hide_worker_failure_or_malformed_trailer(ending):
    script = (
        """
import json,os,time
print(json.dumps({'type':'session.started','session':{'id':'fixture-session'}}),flush=True)
time.sleep(.05)
os.close(0)
print(json.dumps({'type':'session.closed','reason':'expired',
 'session':{'id':'fixture-session'},'usage':{'seconds':.1}}),flush=True)
"""
        + ending
    )
    process = LiveProcess([sys.executable, "-c", script])
    try:
        with pytest.raises(ValueError):
            run_session(
                process,
                Bridge(),
                lambda frames: b"",
                lambda pcm: None,
                lambda event: None,
                duration=5,
            )
    finally:
        process.close()
