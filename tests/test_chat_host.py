"""Real subprocess lifecycle tests with a deterministic worker, never a model."""

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from promethee.chat import TextHost, WorkerProcess, exclusive_host, prepare_profile
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
    if status.exists() and status.read_text().split()[2] == "Z":
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


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
        until((tmp_path / "child.pid").exists)
        child = int((tmp_path / "child.pid").read_text())
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
        result = until(host.poll)
        assert result["status"] == "failed"
        assert workers[0].process.poll() is not None
        child_file = tmp_path / "child.pid"
        if child_file.exists():
            until(lambda: not alive(int(child_file.read_text())))
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


def test_cli_without_credentials_does_not_create_a_world(tmp_path):
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
            "chat",
            "--hermes-python",
            sys.executable,
            "--hermes-root",
            str(tmp_path),
            "--model",
            "diagnostic",
            "--api-mode",
            "chat_completions",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "PROMETHEE_OPENAI_API_KEY" in result.stderr
    assert not target.exists()
