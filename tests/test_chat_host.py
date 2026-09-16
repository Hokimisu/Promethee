"""Real subprocess lifecycle tests with a deterministic worker, never a model."""

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from promethee.chat import (
    TextHost,
    WorkerProcess,
    configure,
    exclusive_host,
    open_text_host,
    prepare_profile,
)
from promethee.conversation import ConversationStore
from promethee.execution import ExecutionService
from promethee.runtime import Runtime

WORKER = """
import json, os, subprocess, sys, time
from pathlib import Path
r = json.loads(sys.stdin.readline())
if r['message'] in ('wait', 'orphan'):
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    Path(sys.argv[1]).write_text(str(child.pid))
    if r['message'] == 'orphan':
        os._exit(1)
    time.sleep(60)
if r['message'] == 'crash':
    os._exit(1)
if r['message'] == 'malformed':
    print('diagnostic-private-data', flush=True)
    os._exit(0)
if r['message'] == 'oversized':
    print('x' * 4194305, flush=True)
    time.sleep(60)
print(json.dumps({'type':'result', 'turn_id':r['turn_id'], 'failed':False,
    'interrupted':False, 'text':'Diagnostic response', 'messages':[
        *r['history'], {'role':'user','content':r['message']},
        {'role':'assistant','content':'Diagnostic response'}]}), flush=True)
"""


def until(callback, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = callback()
        if result:
            return result
        time.sleep(0.02)
    raise AssertionError("Condition did not become true before its deadline.")


def alive(pid):
    if os.name == "nt":
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        api.OpenProcess.restype = ctypes.c_void_p
        api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        api.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = api.OpenProcess(0x100000, False, pid)
        if not handle:
            return False
        try:
            return api.WaitForSingleObject(handle, 0) == 258
        finally:
            api.CloseHandle(handle)
    status = Path(f"/proc/{pid}/stat")
    if sys.platform == "linux":
        try:
            if status.read_text().split()[2] == "Z":
                return False
        except (FileNotFoundError, ProcessLookupError):
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def read_pid(path):
    try:
        return int(path.read_text())
    except (FileNotFoundError, ValueError):
        return None


@pytest.mark.skipif(sys.platform != "linux", reason="Linux /proc process-exit race")
@pytest.mark.parametrize("error", [FileNotFoundError, ProcessLookupError])
def test_process_disappearing_during_proc_read_is_terminal(monkeypatch, error):
    def vanished(*args, **kwargs):
        raise error("Process exited between opening and reading /proc/PID/stat")

    monkeypatch.setattr(Path, "read_text", vanished)
    assert not alive(123)


def make_host(tmp_path, *, timeout=5):
    store = ConversationStore(
        ExecutionService(Runtime(tmp_path / "world.sqlite3", data_origin="session"))
    )
    workers = []

    def factory(request):
        process = WorkerProcess(
            [sys.executable, "-c", WORKER, str(tmp_path / "child.pid")], request
        )
        workers.append(process)
        return process

    host = TextHost(
        store,
        factory,
        model="diagnostic",
        base_url="unused",
        api_mode="chat_completions",
        timeout=timeout,
    )
    return host, workers


def test_native_shape_response_and_correction_through_real_processes(tmp_path):
    host, workers = make_host(tmp_path)
    try:
        old = host.start("wait")
        child = until(lambda: read_pid(tmp_path / "child.pid"))
        original_close = workers[0].close

        def close_after_fence():
            assert host.store.service.get_world()["conversation"]["turn_id"] != old
            original_close()

        workers[0].close = close_after_fence
        host.start("Correction")
        until(lambda: not alive(child))
        result = until(host.poll)
        assert result == {"status": "completed", "text": "Diagnostic response"}
        assert all(worker.process.poll() is not None for worker in workers)
        assert host.store.service.events() == []
        next_turn = host.store.begin("Next")
        assert [m["content"] for m in next_turn["history"]] == [
            "wait",
            "Correction",
            "Diagnostic response",
        ]
    finally:
        host.close()


def test_deadline_closes_worker_and_retains_unanswered_input(tmp_path):
    host, workers = make_host(tmp_path, timeout=0.1)
    try:
        host.start("wait")
        result = until(host.poll)
        assert result["code"] == "deadline_exceeded"
        assert workers[0].process.poll() is not None
        assert host.store.begin("Retry")["history"] == [{"role": "user", "content": "wait"}]
    finally:
        host.close()


@pytest.mark.parametrize("message", ["crash", "orphan", "malformed", "oversized"])
def test_crash_and_orphan_cleanup(tmp_path, message):
    host, workers = make_host(tmp_path, timeout=0.5)
    try:
        host.start(message)
        child = None
        if message == "orphan":
            child = until(lambda: read_pid(tmp_path / "child.pid"))
            until(lambda: workers[0].process.poll() is not None)
            assert alive(child)  # The orphan is actually alive after its parent exits.
        result = until(host.poll)
        assert result["status"] == "failed"
        assert workers[0].process.poll() is not None
        if child:
            until(lambda: not alive(child))
        assert host.store.service.get_world()["conversation"] is None
    finally:
        host.close()


def test_replacement_host_invalidates_pending_tools_without_resubmission(tmp_path):
    host, _ = make_host(tmp_path)
    pending = host.store.begin("Unanswered")
    replacement, _ = make_host(tmp_path)
    assert replacement.store.service.get_world()["conversation"] is None
    assert replacement.store.begin("Correction")["history"] == [
        {"role": "user", "content": "Unanswered"}
    ]
    assert not host.store.abort(pending["turn_id"])
    assert replacement.store.service.events() == []


def test_lock_is_owned_by_os_and_released_on_process_exit(tmp_path):
    code = """
import sys
from promethee.chat import exclusive_host
with exclusive_host(sys.argv[1]):
    print('locked', flush=True)
    sys.stdin.readline()
"""
    proc = subprocess.Popen(
        [sys._base_executable, "-c", code, str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )
    try:
        assert proc.stdout.readline().strip() == "locked"
        with pytest.raises(ValueError, match="already owns"):
            with exclusive_host(tmp_path):
                pass
    finally:
        proc.kill()
        proc.wait(timeout=5)
        proc.stdin.close()
        proc.stdout.close()
    with exclusive_host(tmp_path):
        pass  # The persistent pathname must not be mistaken for a live owner.


def test_fresh_profile_is_bound_to_turn_and_has_no_implicit_tools(tmp_path):
    profile = tmp_path / "profile"
    prepare_profile(profile, tmp_path, "turn-fixture")
    config = json.loads((profile / "config.yaml").read_text())
    assert config["tools"]["tool_search"]["enabled"] == "off"
    server = config["mcp_servers"]["promethee"]
    assert server["args"][-2:] == ["--turn-id", "turn-fixture"]
    assert len(server["tools"]["include"]) == 5
    assert not server["tools"]["resources"] and not server["tools"]["prompts"]
    assert list((profile / "vault").iterdir()) == []
    with pytest.raises(FileExistsError):
        prepare_profile(profile, tmp_path, "turn-fixture")


@pytest.mark.parametrize("command", ["chat", "voice"])
def test_cli_without_credentials_does_not_create_a_world(tmp_path, command):
    environment = dict(os.environ)
    environment.pop("PROMETHEE_OPENAI_API_KEY", None)
    target = tmp_path / "absent-session"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "promethee.cli",
            "--data-dir",
            str(target),
            command,
            "--hermes-python",
            sys.executable,
            "--hermes-root",
            str(tmp_path),
            "--model",
            "diagnostic",
            "--api-mode",
            "chat_completions",
        ]
        + (
            ["--transcription-model", "fixture", "--speech-model", "fixture", "--voice", "fixture"]
            if command == "voice"
            else []
        ),
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "PROMETHEE_OPENAI_API_KEY" in result.stderr
    assert not target.exists()


def local_result(request, **extra):
    return {
        "type": "result",
        "turn_id": request["turn_id"],
        "failed": False,
        "interrupted": False,
        "text": "Fixture response",
        "messages": [
            *request["history"],
            {"role": "user", "content": request["message"]},
            {"role": "assistant", "content": "Fixture response"},
        ],
        **extra,
    }


@pytest.mark.parametrize("effort", [None, "low"])
@pytest.mark.parametrize("measure", [False, True])
def test_host_options_and_timings_are_opt_in_and_not_conversation_history(
    tmp_path, effort, measure
):
    store = ConversationStore(
        ExecutionService(Runtime(tmp_path / "world.sqlite3", data_origin="session"))
    )
    requests = []

    def factory(request):
        requests.append(request)
        return SimpleNamespace(
            close=lambda: None,
            poll=lambda: local_result(request, timings={"worker_total_seconds": 0.25}),
        )

    host = TextHost(
        store,
        factory,
        model="fixture",
        base_url="unused",
        api_mode="codex_responses",
        reasoning_effort=effort,
        measure_timing=measure,
    )
    host.start("A neutral fixture")
    response = host.poll()
    assert requests[0].get("reasoning_effort") == effort
    assert ("reasoning_effort" in requests[0]) == (effort is not None)
    assert ("measure_timing" in requests[0]) == measure
    if measure:
        assert response["timings"]["worker_total_seconds"] == 0.25
        assert response["timings"]["host_total_seconds"] >= 0
        assert requests[0]["measure_timing"] is True
    else:
        assert response == {"status": "completed", "text": "Fixture response"}
    assert store.begin("Next")["history"] == [
        {"role": "user", "content": "A neutral fixture"},
        {"role": "assistant", "content": "Fixture response"},
    ]


@pytest.mark.parametrize(
    "timings",
    [
        "private",
        {"prompt": "private"},
        {"auth_seconds": "private"},
        {"auth_seconds": True},
        {"auth_seconds": -1},
        {"auth_seconds": float("nan")},
        {"auth_seconds": float("inf")},
    ],
)
def test_host_rejects_malformed_timing_metadata_without_exposing_it(tmp_path, timings):
    store = ConversationStore(
        ExecutionService(Runtime(tmp_path / "world.sqlite3", data_origin="session"))
    )
    host = TextHost(
        store,
        lambda request: SimpleNamespace(
            close=lambda: None, poll=lambda: local_result(request, timings=timings)
        ),
        model="fixture",
        base_url="unused",
        api_mode="codex_responses",
        measure_timing=True,
    )
    host.start("A neutral fixture")
    response = host.poll()
    assert response["status"] == "failed"
    assert set(response["timings"]) == {"host_total_seconds"}
    assert "private" not in json.dumps(response)
    assert store.begin("Next")["history"] == [{"role": "user", "content": "A neutral fixture"}]


def test_worker_error_timings_reach_host_without_exception_details(tmp_path):
    store = ConversationStore(
        ExecutionService(Runtime(tmp_path / "world.sqlite3", data_origin="session"))
    )
    host = TextHost(
        store,
        lambda request: SimpleNamespace(
            close=lambda: None,
            poll=lambda: {
                "type": "error",
                "code": "conversation_failed",
                "exception": "RuntimeError",
                "timings": {"import_seconds": 0.02, "worker_total_seconds": 0.04},
            },
        ),
        model="fixture",
        base_url="unused",
        api_mode="codex_responses",
        measure_timing=True,
    )
    host.start("A neutral fixture")
    response = host.poll()
    assert response["status"] == "failed"
    assert response["timings"]["import_seconds"] == 0.02
    assert "exception" not in response


@pytest.mark.parametrize(
    "options",
    [
        {"reasoning_effort": "medium"},
        {"reasoning_effort": []},
        {"measure_timing": 1},
        {"measure_timing": "true"},
        {"measure_timing": None},
    ],
)
def test_invalid_options_are_rejected_before_host_or_runtime_side_effects(options):
    store = Mock()
    with pytest.raises(ValueError):
        TextHost(
            store, Mock(), model="fixture", base_url="unused", api_mode="codex_responses", **options
        )
    store.recover.assert_not_called()
    with pytest.raises(ValueError):
        with open_text_host(SimpleNamespace(**options)):
            pytest.fail("Invalid options must not open a host")


def test_configure_and_open_host_forward_optional_options(tmp_path, monkeypatch):
    parser = argparse.ArgumentParser()
    configure(parser)
    arguments = [
        "--hermes-python",
        sys.executable,
        "--hermes-root",
        str(tmp_path),
        "--model",
        "gpt-6-astra",
        "--api-mode",
        "codex_responses",
    ]
    defaults = parser.parse_args(arguments)
    assert defaults.reasoning_effort is None and defaults.measure_timing is False
    args = parser.parse_args([*arguments, "--reasoning-effort", "low", "--measure-timing"])
    args.data_dir = tmp_path
    Runtime(tmp_path / "world.sqlite3", data_origin="session")
    monkeypatch.setenv("PROMETHEE_OPENAI_API_KEY", "fixture-only")
    requests = []

    def worker(command, request):
        requests.append(request)
        return SimpleNamespace(close=lambda: None, poll=lambda: None)

    monkeypatch.setattr("promethee.chat.WorkerProcess", worker)
    with open_text_host(args) as host:
        host.start("A neutral fixture")
    assert requests[0]["reasoning_effort"] == "low"
    assert requests[0]["measure_timing"] is True
    with pytest.raises(SystemExit):
        parser.parse_args([*arguments, "--reasoning-effort", "invalid"])
