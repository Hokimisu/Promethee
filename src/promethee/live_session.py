"""Executable file-audio Live/Hermes diagnostic; no microphone or speaker opened.

Input is paced PCM from a WAV file, followed by silence until the chosen session
duration. Output PCM and source-tagged events remain in a new local directory.
"""

import argparse
import base64
import json
import threading
import time
import wave
from pathlib import Path

from promethee.chat import configure, open_text_host
from promethee.live_delegation import LiveDelegation
from promethee.live_process import LiveProcess
from promethee.live_startup import build_startup
from promethee.live_worker import final_usage
from promethee.voice import decode_pcm


class PacedInput:
    """Keep the 20 ms audio clock independent of Hermes process startup/cleanup."""

    def __init__(self, transport, read_pcm, deadline):
        self.stopped = threading.Event()
        self.samples, self.error = 0, None

        def feed():
            due = time.monotonic()
            stage = "pacing"
            try:
                while not self.stopped.is_set() and time.monotonic() < deadline:
                    stage = "pacing"
                    now = time.monotonic()
                    if now - due > 0.25:
                        raise ValueError("Audio pacing stalled.")
                    if now < due:
                        self.stopped.wait(min(due - now, 0.02))
                        continue
                    stage = "source"
                    pcm = read_pcm(480)
                    if not isinstance(pcm, bytes) or len(pcm) % 2 or len(pcm) > 960:
                        raise ValueError("Expected at most 480 mono PCM16 frames.")
                    pcm += b"\0" * (960 - len(pcm))
                    stage = "backpressure"
                    transport.send(
                        {
                            "type": "session.input_audio.append",
                            "audio": base64.b64encode(pcm).decode(),
                        }
                    )
                    self.samples += 480
                    due += 0.02
            except Exception:
                self.error = "live_audio_input_failed_" + stage

        self.thread = threading.Thread(target=feed, daemon=True)
        self.thread.start()

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=1)
        if self.thread.is_alive():
            raise RuntimeError("Audio input did not stop.")


def run_session(
    transport,
    bridge,
    read_pcm,
    write_pcm,
    record,
    *,
    duration,
    clock=time.monotonic,
    sleep=time.sleep,
):
    """Run one bounded session; stop input even if transport/delegation fails."""
    pacers = []
    try:
        return _run_session(
            transport,
            bridge,
            read_pcm,
            write_pcm,
            record,
            duration=duration,
            clock=clock,
            sleep=sleep,
            pacers=pacers,
        )
    finally:
        for pacer in pacers:
            pacer.close()


def _run_session(transport, bridge, read_pcm, write_pcm, record, *, duration, clock, sleep, pacers):
    if type(duration) is not int or not 1 <= duration <= 900:
        raise ValueError("Choose a duration between 1 and 900 seconds.")
    started = clock()
    ready, closing, receipt = False, None, None
    received_samples = 0
    while True:
        now = clock()
        if not ready and now - started >= 20:
            raise TimeoutError("Live startup deadline exceeded.")
        if ready and closing is None and now - started >= duration:
            pacers[0].close()
            bridge.close()
            transport.finish()
            closing = now
        if closing is not None and now - closing >= 20:
            raise TimeoutError("Live finalization deadline exceeded.")
        # Drain corrections before asking Hermes for a result. Do not starve
        # the duration deadline if a broken provider floods the queue.
        for _ in range(64):
            event = transport.poll()
            if event is None:
                break
            kind = event["type"]
            if kind == "transport.input_closed":
                if pacers:
                    pacers[0].close()
                bridge.close()
                closing = clock() if closing is None else closing
                record({"source": "transport", "event": event})
                continue
            if kind == "transport.exited":
                record({"source": "transport", "event": event})
                if event["returncode"] != 0 or receipt is None:
                    raise ValueError("Live worker exited without successful finalization.")
                return {
                    "usage": receipt["usage"],
                    "reason": receipt["reason"],
                    "input_samples": pacers[0].samples,
                    "output_samples": received_samples,
                    "elapsed_seconds": clock() - started,
                    "playback_verified": False,
                }
            if receipt is not None:
                raise ValueError("Live provider event arrived after its final receipt.")
            record({"source": "live", "event": event})
            if kind in {"transport.error", "error"}:
                raise ValueError("Live provider or transport failed.")
            if kind == "session.started":
                if ready:
                    raise ValueError("Unexpected second Live startup.")
                ready = True
            if not ready:
                raise ValueError("Live event arrived before startup.")
            if kind == "session.output_audio.delta":
                pcm = decode_pcm(event.get("delta"), 48000)
                write_pcm(pcm)
                received_samples += len(pcm) // 2
            elif kind == "session.closed":
                final_usage(event)
                if event.get("session", {}).get("id") != bridge.session:
                    raise ValueError("Final usage belongs to a different Live session.")
                receipt = event
                pacers[0].close()
                if not getattr(transport, "input_failed", False):
                    transport.finish(discard=True)
                bridge.close()
                closing = clock() if closing is None else closing
            elif closing is None:
                bridge.accept(event)
                if kind == "session.started":
                    pacers.append(
                        PacedInput(
                            transport,
                            read_pcm,
                            time.monotonic() + max(0, duration - (clock() - started)),
                        )
                    )
        if ready and closing is None:
            if getattr(transport, "input_failed", False):
                # Drain the final stdout events on the next iteration before
                # interpreting a concurrent audio-write failure. Launch no work.
                sleep(0.005)
                continue
            if pacers[0].error:
                raise ValueError(pacers[0].error)
            for result in bridge.poll():
                delivery = "queued"
                try:
                    transport.send(result["event"])
                except ValueError:
                    if not getattr(transport, "input_failed", False):
                        raise
                    delivery = "not_sent_transport_closed"
                record({"source": "hermes", "result": result, "delivery": delivery})
        sleep(0.005)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--live-python", type=Path, required=True)
    parser.add_argument("--live-model", required=True)
    parser.add_argument("--live-voice", required=True)
    parser.add_argument("--duration", type=int, required=True)
    parser.add_argument("--call-budget", type=int, required=True)
    parser.add_argument("--input-wav", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--test-url", help="Loopback fixture URL; worker enforces dummy authentication."
    )
    configure(parser)
    args = parser.parse_args()
    if not 1 <= args.duration <= 900 or not 1 <= args.call_budget <= 100:
        parser.error("Choose a bounded duration (1-900 s) and Hermes budget (1-100).")
    if not args.live_python.is_file():
        parser.error("The isolated Live Python must exist.")
    with wave.open(str(args.input_wav), "rb") as source:
        if (
            source.getnchannels(),
            source.getsampwidth(),
            source.getframerate(),
            source.getcomptype(),
        ) != (1, 2, 24000, "NONE"):
            parser.error("Input must be uncompressed mono PCM16 at 24 kHz.")
        if source.getnframes() > args.duration * 24000:
            parser.error("The input audio exceeds the session duration.")
        output = args.output.resolve()
        output.mkdir(exist_ok=False)
        argv = [
            str(args.live_python.resolve()),
            "-X",
            "utf8",
            str(Path(__file__).with_name("live_worker.py")),
            "--model",
            args.live_model,
            "--voice",
            args.live_voice,
            "--max-seconds",
            str(args.duration),
        ]
        if args.test_url:
            argv.extend(["--test-url", args.test_url])
        with (
            open_text_host(args) as host,
            (output / "events.jsonl").open("w", encoding="utf-8") as events,
            (output / "output.pcm").open("wb") as audio,
        ):
            startup = output / "startup.json"
            startup.write_text(
                json.dumps(
                    build_startup(host.store, memory_enabled=args.vault is not None),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            argv.extend(["--startup-file", str(startup)])
            bridge = LiveDelegation(host, call_budget=args.call_budget)
            transport = LiveProcess(argv)
            try:

                def record(event):
                    events.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
                    events.flush()

                result = run_session(
                    transport,
                    bridge,
                    source.readframes,
                    audio.write,
                    record,
                    duration=args.duration,
                )
                (output / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
                print(json.dumps(result), flush=True)
            except BaseException:
                # A missing final receipt is not zero usage or a successful session.
                failed = {"status": "failed", "usage": None, "playback_verified": False}
                (output / "report.json").write_text(json.dumps(failed), encoding="utf-8")
                raise
            finally:
                try:
                    bridge.close()
                finally:
                    transport.close()


if __name__ == "__main__":
    main()
