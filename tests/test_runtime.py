import copy
import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from promethee.demo import ACTIVITY_ID, STEPS
from promethee.journal import export_journal
from promethee.runtime import Runtime
from promethee.world import ActionError


@pytest.fixture
def runtime(tmp_path):
    return Runtime(tmp_path / "world.sqlite3")


def test_duplicate_command_is_committed_once_even_concurrently(runtime):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: runtime.execute("spawn-one", STEPS[0]), range(4)))
    assert all(result["ok"] for result in results)
    assert sum(not result["replayed"] for result in results) == 1
    assert len(runtime.events()) == 1
    assert list(runtime.snapshot()["objects"]) == ["chair-1"]


def test_reusing_request_id_for_different_payload_is_rejected(runtime):
    runtime.execute("spawn-one", STEPS[0])
    state = runtime.snapshot()
    with pytest.raises(ActionError, match="different action"):
        runtime.execute("spawn-one", STEPS[1])
    assert runtime.snapshot() == state
    assert len(runtime.events()) == 1


@pytest.mark.parametrize("point", [[6, 0], [True, 0], [10**400, 0], [0], "0,0"])
def test_invalid_coordinates_leave_world_unchanged(runtime, point):
    state = runtime.snapshot()
    result = runtime.execute("bad-position", {"kind": "move", "args": {"position": point}})
    assert result["ok"] is False
    assert runtime.snapshot() == state


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_non_json_numbers_never_enter_storage(runtime, value):
    with pytest.raises(ValueError):
        runtime.execute("bad-number", {"kind": "move", "args": {"position": [value, 0]}})
    assert runtime.events() == []


@pytest.mark.parametrize(
    "action",
    [
        {"kind": "run_shell", "args": {}},
        {"kind": "spawn", "args": {"object_id": "x", "asset": "unknown", "position": [0, 0]}},
        {"kind": "take", "args": {"object_id": "missing"}},
        {"kind": "move", "args": {"position": [0, 0], "extra": True}},
        {"kind": "stand", "args": {}},
        {"kind": ["move"], "args": {}},
    ],
)
def test_rejections_are_durable_and_never_change_world(runtime, action):
    before = runtime.snapshot()
    first = runtime.execute("invalid", action)
    repeated = runtime.execute("invalid", action)
    assert not first["ok"]
    assert repeated["replayed"]
    assert runtime.snapshot() == before
    assert len(runtime.events()) == 1


def test_out_of_reach_and_occupied_hands(runtime):
    runtime.execute("plush", STEPS[2])
    runtime.execute("away", {"kind": "move", "args": {"position": [5, 5]}})
    assert not runtime.execute("take-away", STEPS[4])["ok"]
    runtime.execute("return", {"kind": "move", "args": {"position": [0, 0]}})
    assert runtime.execute("take-near", STEPS[4])["ok"]
    assert not runtime.execute("take-again", STEPS[4])["ok"]
    assert not runtime.execute("place-away", {"kind": "place", "args": {"position": [-5, -5]}})[
        "ok"
    ]
    assert runtime.snapshot()["avatar"]["holding"] == "plush-1"


def test_activity_pause_survives_restart_and_finishes_without_duplicates(runtime):
    runtime.start_activity(ACTIVITY_ID, STEPS)
    for _ in range(5):
        runtime.advance(ACTIVITY_ID)
    runtime.set_paused(ACTIVITY_ID, True)
    reopened = Runtime(runtime.path)
    assert reopened.advance(ACTIVITY_ID)["cursor"] == 5
    assert reopened.snapshot()["avatar"]["holding"] == "plush-1"
    reopened.set_paused(ACTIVITY_ID, False)
    reopened.advance(ACTIVITY_ID)
    result = reopened.advance(ACTIVITY_ID)
    assert result["status"] == "completed"
    reopened.advance(ACTIVITY_ID)
    assert len(reopened.events()) == len(STEPS)
    state = reopened.snapshot()
    assert state["avatar"]["seated_on"] == "chair-1"
    assert state["objects"]["plush-1"]["position"] == state["avatar"]["position"]
    assert not reopened.execute("walk-seated", STEPS[5])["ok"]


def test_intervening_world_change_fails_activity_without_claiming_completion(runtime):
    runtime.start_activity(ACTIVITY_ID, STEPS)
    runtime.execute("external-spawn", STEPS[0])
    result = runtime.advance(ACTIVITY_ID)
    assert result["status"] == "failed"
    assert result["cursor"] == 0
    assert runtime.events()[-1]["result"]["ok"] is False


def test_transaction_rolls_back_world_event_and_cursor_on_storage_failure(runtime):
    runtime.start_activity(ACTIVITY_ID, STEPS)
    before = runtime.snapshot()
    with runtime.connection() as conn:
        conn.execute("""CREATE TRIGGER fail_activity BEFORE UPDATE ON activities
            BEGIN SELECT RAISE(ABORT, 'simulated storage failure'); END;""")
    with pytest.raises(sqlite3.IntegrityError, match="simulated storage failure"):
        runtime.advance(ACTIVITY_ID)
    assert runtime.snapshot() == before
    assert runtime.events() == []
    assert runtime.activity(ACTIVITY_ID)["cursor"] == 0
    with runtime.connection() as conn:
        conn.execute("DROP TRIGGER fail_activity")
    assert runtime.advance(ACTIVITY_ID)["cursor"] == 1


def test_plan_and_reserved_ids_cannot_be_overwritten(runtime):
    runtime.start_activity(ACTIVITY_ID, STEPS)
    changed = copy.deepcopy(STEPS)
    changed[0]["args"]["position"] = [2, 0]
    with pytest.raises(ActionError, match="different plan"):
        runtime.start_activity(ACTIVITY_ID, changed)
    with pytest.raises(ActionError, match="reserved"):
        runtime.execute("activity-welcome-0", STEPS[0])


def test_journal_has_observed_successes_only_and_preserves_user_edits(runtime, tmp_path):
    runtime.execute("chair", STEPS[0])
    runtime.execute("failure", STEPS[4])
    vault = tmp_path / "vault"
    assert export_journal(runtime, vault) == 1
    notes = list(vault.rglob("*.md"))
    assert len(notes) == 1
    assert "Aucune exécution physique" in notes[0].read_text(encoding="utf-8")
    notes[0].write_text("My own annotation", encoding="utf-8")
    assert export_journal(runtime, vault) == 0
    assert notes[0].read_text(encoding="utf-8") == "My own annotation"
    other = Runtime(tmp_path / "other.sqlite3")
    other.execute("chair", STEPS[0])
    assert export_journal(other, vault) == 1
    assert len(list(vault.rglob("*.md"))) == 2


def test_cli_resume_in_a_new_process(tmp_path):
    def run(*args):
        output = subprocess.run(
            [sys.executable, "-m", "promethee.cli", "--data-dir", str(tmp_path), *args],
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        )
        return json.loads(output.stdout)

    assert run("demo", "--pause-after", "4")["status"] == "paused"
    assert run("demo")["status"] == "paused"
    assert run("demo", "--resume")["status"] == "completed"
    assert run("world")["objects"]["sign-1"]["text"] == "Bienvenue dans Promethee."
