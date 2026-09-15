"""Exercise the executable file-audio session with real SDK and native Astra.

Live server, transcripts and PCM are synthetic; no Live inference or devices.
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

from promethee.live_process import LiveProcess
from promethee.runtime import Runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "live-python", "hermes-python", "hermes-root", "hermes-auth-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(exist_ok=False)
    shutil.copyfile(__file__, output / "qualification-source.py")
    source = Path(__file__).with_name("live_session_fixture.py")
    shutil.copyfile(source, output / "fixture-source.py")
    root = Path(__file__).resolve().parents[2]
    for name in ("live_session", "live_process", "live_worker", "live_delegation", "chat"):
        shutil.copyfile(root / "src/promethee" / f"{name}.py", output / f"{name}.py")
    world = output / "world"
    world.mkdir()
    runtime = Runtime(world / "world.sqlite3", data_origin="session", session_kind="qualification")
    with wave.open(str(output / "input.wav"), "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0" * 4800)
    server = LiveProcess(
        [
            str(args.live_python.resolve()),
            "-X",
            "utf8",
            str(source),
            "--report",
            str(output / "server.json"),
        ]
    )
    try:
        deadline = time.monotonic() + 15
        while (ready := server.poll()) is None:
            if time.monotonic() > deadline:
                raise TimeoutError("Local fixture failed to start.")
            time.sleep(0.02)
        assert ready["type"] == "fixture.ready"
        command = [
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "promethee.live_session",
            "--data-dir",
            str(world),
            "--live-python",
            str(args.live_python.resolve()),
            "--live-model",
            "gpt-live-1",
            "--live-voice",
            "marin",
            "--duration",
            "60",
            "--call-budget",
            "1",
            "--input-wav",
            str(output / "input.wav"),
            "--output",
            str(output / "session"),
            "--test-url",
            f"ws://127.0.0.1:{ready['port']}/v1",
            "--hermes-python",
            str(args.hermes_python.resolve()),
            "--hermes-root",
            str(args.hermes_root.resolve()),
            "--hermes-auth-root",
            str(args.hermes_auth_root.resolve()),
            "--auth",
            "hermes-codex",
            "--api-mode",
            "codex_responses",
            "--model",
            "gpt-6-astra",
            "--timeout",
            "50",
        ]
        (output / "command.json").write_text(json.dumps(command, indent=2), encoding="utf-8")
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", timeout=90
        )
        (output / "stdout.txt").write_text(result.stdout, encoding="utf-8")
        (output / "stderr.txt").write_text(result.stderr, encoding="utf-8")
        assert result.returncode == 0, result.stderr
        deadline = time.monotonic() + 10
        while not (output / "server.json").is_file():
            event = server.poll()
            if event and event["type"] == "transport.exited" and event["returncode"] != 0:
                raise ValueError("Local fixture failed.")
            if time.monotonic() > deadline:
                raise TimeoutError("Fixture completion missing.")
            time.sleep(0.02)
        with runtime.connection() as conn:
            assert conn.execute("SELECT count(*) FROM executions").fetchone()[0] == 0
            assert (
                conn.execute(
                    "SELECT count(*) FROM conversation_turns WHERE status='completed'"
                ).fetchone()[0]
                == 1
            )
        report = json.loads((output / "session/report.json").read_text())
        wire = json.loads((output / "server.json").read_text())
        assert report["input_samples"] == wire["audio_chunks"] * 480
        assert report["output_samples"] == 480
        assert (output / "session/output.pcm").stat().st_size == 960
        print(
            json.dumps(
                {"report": report, "results": wire["results"], "connections": wire["connections"]},
                ensure_ascii=False,
            ),
            flush=True,
        )
    finally:
        server.close()


if __name__ == "__main__":
    main()
