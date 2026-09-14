import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from promethee.journal import export_journal
from promethee.runtime import Runtime
from promethee.world import ActionError


def test_session_origin_is_immutable_and_logical_tools_cannot_modify_it(tmp_path):
    path = tmp_path / "session/world.sqlite3"
    runtime = Runtime(path, data_origin="session")
    before = runtime.require_session()
    assert before["objects"] == {}
    assert Runtime(path).snapshot() == before
    with pytest.raises(ValueError, match="cannot be changed"):
        Runtime(path, data_origin="fixture")
    action = {"kind": "move", "args": {"position": [1, 0]}}
    with pytest.raises(ActionError, match="controller"):
        runtime.execute("move", action)
    with pytest.raises(ActionError, match="controller"):
        runtime.start_activity("plan", [action])
    result = subprocess.run(
        [sys.executable, "-m", "promethee.cli", "--data-dir", str(path.parent), "demo"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert runtime.snapshot() == before
    assert runtime.events() == []


def test_fixture_is_excluded_from_agent_access_and_exports_keep_origin(tmp_path):
    runtime = Runtime(tmp_path / "world.sqlite3")
    with pytest.raises(ActionError, match="session"):
        runtime.require_session()
    runtime.execute("move", {"kind": "move", "args": {"position": [1, 0]}})
    export_journal(runtime, tmp_path / "vault")
    note = next((tmp_path / "vault").rglob("*.md"))
    assert "data_origin: fixture" in note.read_text(encoding="utf-8")


def test_revision_counts_actual_mutations_only_and_is_serialized(tmp_path):
    runtime = Runtime(tmp_path / "world.sqlite3")
    runtime.execute("no-op", {"kind": "move", "args": {"position": [0, 0]}})
    assert runtime.snapshot()["revision"] == 0

    def spawn(number):
        return runtime.execute(
            f"spawn-{number}",
            {
                "kind": "spawn",
                "args": {"object_id": f"object-{number}", "asset": "plush", "position": [0, 0]},
            },
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(result["ok"] for result in pool.map(spawn, range(4)))
    assert runtime.snapshot()["revision"] == 4
    assert spawn(0)["replayed"]
    runtime.execute("reject", {"kind": "stand", "args": {}})
    assert runtime.snapshot()["revision"] == 4
