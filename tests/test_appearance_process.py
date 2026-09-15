"""Real subprocess lifecycle with analytic output; not a VRM qualification."""

import json
import subprocess
import sys
import threading
import time

import pytest
from test_prepared_avatar import record

from promethee.appearance_process import AppearancePreparation

CHILD = """
import hashlib, json, sys, time
from pathlib import Path
avatar, motion, report, mode, option, output = map(Path, sys.argv[1:])
control = json.loads(avatar.with_suffix('.control.json').read_text())
avatar.with_suffix('.started').write_text('started')
if control.get('wait'): time.sleep(30)
if control.get('fail'): sys.exit(2)
result = json.loads(avatar.read_text())
result['motion_sha256'] = hashlib.sha256(motion.read_bytes()).hexdigest()
if control.get('invalid'): result['avatar_sha256'] = '0' * 64
output.write_text(json.dumps(result))
"""


def until(probe):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        value = probe()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("Subprocess did not reach the expected state.")


@pytest.fixture
def preparation(tmp_path, monkeypatch):
    payload, artifact = record()
    avatar, script = tmp_path / "analytic.json", tmp_path / "producer.py"
    avatar.write_text(json.dumps(artifact))
    script.write_text(CHILD)
    control = avatar.with_suffix(".control.json")
    control.write_text("{}")
    processes = []
    original = subprocess.Popen

    def start(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr("promethee.appearance_process.subprocess.Popen", start)
    worker = AppearancePreparation(
        avatar=avatar, script=script, output=tmp_path / "jobs", node=sys.executable
    )
    try:
        yield worker, json.loads(payload), control, processes
    finally:
        worker.close()
        assert all(p.poll() is not None for p in processes)


def test_cancellation_reaps_its_child_and_a_new_job_cannot_receive_the_old_result(preparation):
    worker, document, control, processes = preparation
    control.write_text('{"wait": true}')
    first = worker.submit(document, mode="--settle")
    until(lambda: control.with_name("analytic.started").exists())
    assert worker.poll() is None
    with pytest.raises(RuntimeError, match="busy"):
        worker.submit(document, mode="--settle")
    worker.cancel()
    assert until(worker.poll) == {"type": "cancelled", "job_id": first}
    assert processes[0].poll() is not None
    control.write_text("{}")
    second = worker.submit(document, mode="--settle")
    result = until(worker.poll)
    assert result["type"] == "prepared" and result["job_id"] == second != first
    assert result["appearance"]["frames"]
    assert worker.poll() is None


@pytest.mark.parametrize("control_data", [{"fail": True}, {"invalid": True}])
def test_failed_geometry_or_validation_never_delivers_poses(preparation, control_data):
    worker, document, control, _ = preparation
    control.write_text(json.dumps(control_data))
    job = worker.submit(document, mode="--settle")
    result = until(worker.poll)
    assert result["type"] == "error" and result["job_id"] == job
    assert "appearance" not in result


def test_submission_freezes_the_callers_document(preparation):
    worker, document, _, _ = preparation
    job = worker.submit(document, mode="--settle")
    document["frames"][0]["positions"][0][0] += 1
    result = until(worker.poll)
    assert result["type"] == "prepared" and result["job_id"] == job


def test_timeout_and_close_terminate_only_the_owned_process(preparation):
    worker, document, control, processes = preparation
    control.write_text('{"wait": true}')
    worker.timeout = 0.2
    worker.submit(document, mode="--settle")
    result = until(worker.poll)
    assert result["type"] == "error" and "time limit" in result["error"]
    assert processes[0].poll() is not None
    worker.timeout = 60
    worker.submit(document, mode="--settle")
    until(lambda: len(processes) == 2)
    worker.close()
    assert processes[1].poll() is not None
    with pytest.raises(RuntimeError, match="closed"):
        worker.submit(document, mode="--settle")


def test_cancel_also_wins_during_validation_and_after_completed_work(preparation, monkeypatch):
    worker, document, _, _ = preparation
    entered, release = threading.Event(), threading.Event()
    run = worker._run

    def delayed_validation(command, stderr_path, started):
        assert threading.current_thread() is not threading.main_thread()
        if stderr_path.name == "validation-stderr.txt":
            entered.set()
            assert release.wait(5)
        return run(command, stderr_path, started)

    monkeypatch.setattr(worker, "_run", delayed_validation)
    job = worker.submit(document, mode="--settle")
    try:
        assert entered.wait(5)
        assert worker.poll() is None
        worker.cancel()
    finally:
        release.set()
    assert until(worker.poll) == {"type": "cancelled", "job_id": job}
    job = worker.submit(document, mode="--settle")
    worker.future.result(timeout=5)
    worker.cancel()
    assert worker.poll() == {"type": "cancelled", "job_id": job}
