import json
import sys
import time

import pytest

from promethee.motion_process import MotionProcess


def wait_for(worker, kind):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        item = worker.poll()
        if item and item["type"] == kind:
            return item
        time.sleep(0.005)
    raise AssertionError(f"No {kind} message")


def test_private_worker_round_trip_and_clean_shutdown(tmp_path):
    script = tmp_path / "worker.py"
    script.write_text(
        "import json,sys,os\n"
        "print(json.dumps({'type':'started','pid':os.getpid()}),flush=True)\n"
        "print(json.dumps({'type':'ready','skeleton':{}}),flush=True)\n"
        "for line in sys.stdin:\n"
        " job=json.loads(line)\n"
        " if job.get('type')=='shutdown': break\n"
        " print('private diagnostic',file=sys.stderr,flush=True)\n"
        " print(json.dumps({'type':'generated','job_id':job['job_id']}),flush=True)\n",
        encoding="utf-8",
    )
    worker = MotionProcess([sys.executable, "-u", str(script)], tmp_path / "output")
    try:
        wait_for(worker, "ready")
        # Windows venv launchers may spawn the actual Python child.
        assert type(worker.pid) is int and worker.pid > 0
        worker.submit({"job_id": "a" * 32})
        with pytest.raises(RuntimeError, match="busy"):
            worker.submit({"job_id": "b" * 32})
        assert wait_for(worker, "generated")["job_id"] == "a" * 32
        assert worker.pending is None
    finally:
        worker.close()
    assert worker.process.poll() == 0
    assert not worker.reader.is_alive()
    assert "private diagnostic" in (worker.output / "worker.log").read_text()


@pytest.mark.parametrize(
    "message",
    [
        "not json",
        json.dumps({"type": "generated", "job_id": "wrong"}),
        "a" * 65537,
    ],
    ids=["invalid-json", "wrong-job", "oversized"],
)
def test_corrupt_worker_fails_closed(tmp_path, message):
    script = tmp_path / "worker.py"
    script.write_text("print(" + repr(message) + ", flush=True)\n", encoding="utf-8")
    worker = MotionProcess([sys.executable, "-u", str(script)], tmp_path / "output")
    try:
        assert wait_for(worker, "crashed")["error"]
        assert not worker.ready
    finally:
        worker.close()
