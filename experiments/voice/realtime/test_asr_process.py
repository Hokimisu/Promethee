"""Real subprocess protocol checks with a tiny fake worker; no ASR model or GPU."""

import base64
import importlib.util
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture
def asr():
    spec = importlib.util.spec_from_file_location(
        "asr_process_test", Path(__file__).with_name("asr.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_worker(tmp_path):
    path = tmp_path / "fake_asr.py"
    path.write_text(
        textwrap.dedent(
            """
            import json
            import os
            import subprocess
            import sys
            import time

            mode = sys.argv[1]
            def emit(value):
                print(json.dumps(value), flush=True)

            if mode == "startup_crash":
                os._exit(7)
            if mode == "startup_error":
                emit({"event": "error", "id": None, "code": "asr_startup_failed"})
                time.sleep(60)
            if mode == "startup_hang":
                time.sleep(60)
            metrics = {}
            if mode == "child":
                child = subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(60)"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                metrics["child_pid"] = child.pid
            emit({"event": "ready", "id": "wrong" if mode == "bad_ready" else None,
                  "metrics": metrics})
            for line in sys.stdin:
                request = json.loads(line)
                if mode in ("hang", "child"):
                    time.sleep(60)
                if mode == "crash":
                    os._exit(8)
                if mode == "invalid_json":
                    print("not JSON", flush=True)
                    time.sleep(60)
                if mode == "oversized":
                    print("x" * 200001, flush=True)
                    time.sleep(60)
                if mode == "nested":
                    payload = json.dumps({"event": "transcript", "id": request["id"],
                                          "extra": "MARK"})
                    payload = payload.replace(chr(34) + "MARK" + chr(34),
                                              "[" * 7000 + "0" + "]" * 7000)
                    print(payload, flush=True)
                    time.sleep(60)
                identifier = "obsolete" if mode == "wrong_id" else request["id"]
                text = 42 if mode == "invalid_text" else "Bonjour Ariane."
                if mode == "unicode_boundary":
                    text = "\U0001f600" * 16000
                duration = float("nan") if mode == "non_finite" else 0.01
                emit({"event": "transcript", "id": identifier, "text": text,
                      "metrics": {"audio_seconds": 0.1,
                                  "transcription_seconds": duration}})
            """
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def launch(asr, fake_worker, tmp_path, monkeypatch):
    owned = []
    launches = []
    original = subprocess.Popen

    def record(*args, **kwargs):
        process = original(*args, **kwargs)
        launches.append(process.pid)
        return process

    monkeypatch.setattr(asr.subprocess, "Popen", record)

    def start(mode="echo", clock=None):
        log = (tmp_path / f"worker-{len(owned)}.log").open("w", encoding="utf-8")
        try:
            process = asr.ASRProcess(
                [sys.executable, "-u", str(fake_worker), mode], log, clock=clock or Clock()
            )
        except BaseException:
            log.close()
            raise
        owned.append((process, log))
        return process

    start.launches = launches
    yield start
    for process, log in owned:
        try:
            process.close()
        finally:
            log.close()


def wait_event(process, *, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        event = process.poll()
        if event is not None:
            return event
        time.sleep(0.01)
    pytest.fail("Fake ASR produced no event within the bounded wait.")


def ready(process):
    event = wait_event(process)
    assert event["event"] == "ready"
    assert process.state == "ready"
    return event


def assert_failed_and_closed(process, event, launches):
    assert event["event"] == "error"
    assert process.state == "failed"
    assert process.closed.is_set()
    assert process.process.poll() is not None
    assert not process.reader.is_alive()
    assert not process.writer.is_alive()
    assert len(launches) == 1
    for _ in range(3):
        assert process.poll() is None
    with pytest.raises(ValueError):
        process.submit("no-retry", "AAA=")
    assert len(launches) == 1


def test_real_stdin_stdout_roundtrip_reuses_one_process(launch):
    process = launch()
    ready(process)
    pcm = base64.b64encode(b"\x00\x00" * 1600).decode("ascii")
    for identifier in ("first", "second"):
        process.submit(identifier, pcm)
        assert process.busy
        result = wait_event(process)
        assert (result["event"], result["id"], result["text"]) == (
            "transcript",
            identifier,
            "Bonjour Ariane.",
        )
        assert not process.busy
    assert len(launch.launches) == 1
    process.close()
    process.close()
    assert process.process.poll() is not None


def test_only_one_job_can_be_in_flight(launch):
    process = launch("hang")
    ready(process)
    process.submit("one", "AAA=")
    with pytest.raises(ValueError):
        process.submit("two", "AAA=")
    assert process.active_id == "one"
    assert len(launch.launches) == 1


def test_submit_after_idle_close_cannot_queue_an_unanswerable_job(launch):
    process = launch()
    ready(process)
    process.close()
    with pytest.raises(ValueError):
        process.submit("after-close", "AAA=")
    assert process.requests.empty()
    assert not process.busy
    assert len(launch.launches) == 1


def test_deep_json_response_reports_exit_and_closes_without_waiting_for_deadline(launch):
    clock = Clock()
    process = launch("nested", clock)
    ready(process)
    process.submit("deep-json", "AAA=")
    assert_failed_and_closed(process, wait_event(process), launch.launches)
    assert clock.now == 100.0  # No deadline advance can hide a silently dead reader.


def test_maximum_unicode_transcript_survives_json_escaping(launch):
    process = launch("unicode_boundary")
    ready(process)
    process.submit("unicode-limit", "AAA=")
    result = wait_event(process)
    assert (result["event"], result["id"]) == ("transcript", "unicode-limit")
    assert result["text"] == "\U0001f600" * 16000
    assert process.state == "ready" and not process.busy
    assert len(launch.launches) == 1


@pytest.mark.parametrize("identifier", [None, "", " ", "x" * 81, 42])
def test_invalid_ids_cannot_bypass_single_job_limit(launch, identifier):
    process = launch("hang")
    ready(process)
    with pytest.raises(ValueError):
        process.submit(identifier, "AAA=")
    assert not process.busy


@pytest.mark.parametrize("mode", ["startup_crash", "startup_error", "bad_ready"])
def test_startup_failure_closes_owned_worker_without_retry(launch, mode):
    process = launch(mode)
    assert_failed_and_closed(process, wait_event(process), launch.launches)


@pytest.mark.parametrize(
    "mode", ["crash", "invalid_json", "oversized", "wrong_id", "invalid_text", "non_finite"]
)
def test_bad_or_failed_worker_output_closes_without_retry(launch, mode):
    process = launch(mode)
    ready(process)
    process.submit("current", "AAA=")
    assert_failed_and_closed(process, wait_event(process), launch.launches)


def test_startup_deadline_uses_controlled_clock_and_kills_process(launch):
    clock = Clock()
    process = launch("startup_hang", clock)
    clock.now += 59.9
    assert process.poll() is None
    assert not process.closed.is_set()
    clock.now += 0.1
    event = process.poll()
    assert event["id"] is None
    assert_failed_and_closed(process, event, launch.launches)


def test_active_deadline_uses_controlled_clock_and_keeps_request_id(launch):
    clock = Clock()
    process = launch("hang", clock)
    ready(process)
    process.submit("timed-out", "AAA=")
    clock.now += 29.9
    assert process.poll() is None
    clock.now += 0.1
    event = process.poll()
    assert event["id"] == "timed-out"
    assert_failed_and_closed(process, event, launch.launches)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job ownership test")
def test_timeout_closes_windows_job_and_its_real_child(launch):
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    clock = Clock()
    process = launch("child", clock)
    event = ready(process)
    assert process.job is not None
    handle = kernel.OpenProcess(0x00100000, False, event["metrics"]["child_pid"])
    assert handle, ctypes.get_last_error()
    try:
        assert kernel.WaitForSingleObject(handle, 0) == 258  # WAIT_TIMEOUT: child is alive.
        process.submit("timed-out", "AAA=")
        clock.now += 30
        assert_failed_and_closed(process, process.poll(), launch.launches)
        assert kernel.WaitForSingleObject(handle, 2000) == 0  # WAIT_OBJECT_0: owned child exited.
    finally:
        kernel.CloseHandle(handle)
