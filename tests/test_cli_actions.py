import json
import subprocess
import sys

import pytest

from promethee.catalog import CATALOG
from promethee.runtime import Runtime


@pytest.fixture
def cli(tmp_path):
    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "promethee.cli", "--data-dir", str(tmp_path / "data"), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    return run


def test_catalog_does_not_create_a_world(cli, tmp_path):
    result = cli("catalog")
    assert result.returncode == 0
    assert json.loads(result.stdout) == CATALOG
    assert not (tmp_path / "data").exists()


def test_free_action_replays_across_processes_without_a_plan(cli, tmp_path):
    path = tmp_path / "action.json"
    path.write_text(json.dumps({"kind": "move", "args": {"position": [2, -3]}}))
    first = cli("act", "--request-id", "manual-move", "--file", str(path))
    repeat = cli("act", "--request-id", "manual-move", "--file", str(path))
    assert first.returncode == repeat.returncode == 0
    assert json.loads(first.stdout) == {"ok": True, "replayed": False}
    assert json.loads(repeat.stdout) == {"ok": True, "replayed": True}
    runtime = Runtime(tmp_path / "data/world.sqlite3")
    assert runtime.snapshot()["avatar"]["position"] == [2.0, -3.0]
    assert runtime.snapshot()["objects"] == {}
    assert len(runtime.events()) == 1
    with runtime.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 0
    path.write_text(json.dumps({"kind": "move", "args": {"position": [3, 2]}}))
    conflict = cli("act", "--request-id", "manual-move", "--file", str(path))
    assert conflict.returncode == 2
    assert "different action" in conflict.stderr
    assert runtime.snapshot()["avatar"]["position"] == [2.0, -3.0]
    assert len(runtime.events()) == 1


def test_rejected_action_and_its_replay_exit_one(cli, tmp_path):
    runtime = Runtime(tmp_path / "data/world.sqlite3")
    before = runtime.snapshot()
    path = tmp_path / "action.json"
    path.write_text(json.dumps({"kind": "take", "args": {"object_id": "absent"}}))
    for replayed in (False, True):
        result = cli("act", "--request-id", "cannot-take", "--file", str(path))
        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert not payload["ok"]
        assert payload["replayed"] is replayed
    assert runtime.snapshot() == before
    assert len(runtime.events()) == 1


@pytest.mark.parametrize(
    "content", [None, b"{", b"\xff", b'{"kind":"move","args":{"position":[NaN,0]}}']
)
def test_bad_input_exits_two_without_recording_an_action(cli, tmp_path, content):
    runtime = Runtime(tmp_path / "data/world.sqlite3")
    before = runtime.snapshot()
    path = tmp_path / "action.json"
    if content is not None:
        path.write_bytes(content)
    result = cli("act", "--request-id", "invalid-input", "--file", str(path))
    assert result.returncode == 2
    assert "Error:" in result.stderr
    assert runtime.snapshot() == before
    assert runtime.events() == []
