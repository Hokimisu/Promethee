"""CPU contract tests only: no provider inference or physical motion."""

import copy
import json
import sqlite3

import pytest

from promethee.execution import ExecutionService
from promethee.mcp_server import WorldTools
from promethee.migrations import migrate, read_world
from promethee.runtime import Runtime
from promethee.world import ActionError


def setup_session(tmp_path, articulated_pose):
    now = [100.0]
    runtime = Runtime(tmp_path / "world.sqlite3", data_origin="session")
    service = ExecutionService(runtime, clock=lambda: now[0])
    driver = service.acquire_controller(source="kinematic", supported_actions=["move"])
    state = runtime.snapshot()
    observation = {key: copy.deepcopy(state[key]) for key in ("avatar", "objects")}
    observation["pose"] = articulated_pose
    driver.reconcile(observation, stopped=True)
    return service, driver, now


ACTION = {"kind": "move", "args": {"position": [0.2, 0.3]}}


def test_corrected_turn_cannot_submit_even_with_fresh_revision(tmp_path, articulated_pose):
    service, driver, _ = setup_session(tmp_path, articulated_pose)
    old = WorldTools(service, turn_id=service.begin_turn())
    current = WorldTools(service, turn_id=service.begin_turn())
    revision = current.world()["revision"]
    with pytest.raises(ActionError, match="obsolete"):
        old.submit("old-proposal", revision, ACTION)
    assert driver.claim_next() is None
    assert current.submit("new-proposal", revision, ACTION)["status"] == "accepted"


def test_replay_is_safe_but_old_cancel_cannot_stop_current_action(tmp_path, articulated_pose):
    service, driver, _ = setup_session(tmp_path, articulated_pose)
    old = WorldTools(service, turn_id=service.begin_turn())
    revision = old.world()["revision"]
    old.submit("first", revision, ACTION)
    current = WorldTools(service, turn_id=service.begin_turn())
    # A conversational correction alone is not a body cancellation.
    assert driver.claim_next()["request_id"] == "first"
    assert old.submit("first", revision, ACTION)["replayed"]
    with pytest.raises(ActionError, match="obsolete"):
        old.cancel("first")
    assert current.cancel("first")["cancel_requested"]


def test_timeout_and_finished_turn_discard_late_proposals(tmp_path, articulated_pose):
    service, _, now = setup_session(tmp_path, articulated_pose)
    turn = service.begin_turn(timeout=1)
    tools = WorldTools(service, turn_id=turn)
    now[0] += 1
    with pytest.raises(ActionError, match="expired"):
        tools.submit("late", tools.world()["revision"], ACTION)
    with pytest.raises(ActionError, match="expired"):
        service.end_turn(turn)
    fresh = service.begin_turn()
    service.end_turn(fresh)
    with pytest.raises(ActionError, match="obsolete"):
        WorldTools(service, turn_id=fresh).submit("finished", tools.world()["revision"], ACTION)


def test_new_host_fences_old_process_using_same_database(tmp_path, articulated_pose):
    service, _, now = setup_session(tmp_path, articulated_pose)
    old = WorldTools(service, turn_id=service.begin_turn())
    new = ExecutionService(Runtime(service.runtime.path, create=False), clock=lambda: now[0])
    new.begin_turn()
    with pytest.raises(ActionError, match="obsolete"):
        old.submit("old-host", new.get_world()["revision"], ACTION)


@pytest.mark.parametrize("fail", [False, True])
def test_v4_migration_preserves_pose_and_execution(tmp_path, articulated_pose, fail):
    service, _, _ = setup_session(tmp_path, articulated_pose)
    state = service.get_world()
    service.submit("pending", state["revision"], ACTION)
    with service.runtime.connection() as conn:
        world = read_world(conn)
        world["schema_version"] = 4
        world.pop("conversation")
        conn.execute("UPDATE world SET data=? WHERE id=1", (json.dumps(world),))
        conn.execute("DROP TABLE conversation_turns")
        if fail:
            conn.execute("""CREATE TRIGGER fail_v5 BEFORE UPDATE ON world
                BEGIN SELECT RAISE(ABORT, 'v5 rollback'); END;""")
        before = list(conn.iterdump())
    backup = tmp_path / "v4-backup.sqlite3"
    if fail:
        with pytest.raises(sqlite3.IntegrityError, match="v5 rollback"):
            migrate(service.runtime.path, backup)
        with sqlite3.connect(service.runtime.path) as conn:
            assert list(conn.iterdump()) == before
        with sqlite3.connect(backup) as conn:
            assert list(conn.iterdump()) == before
        return
    migrate(service.runtime.path, backup)
    result = service.runtime.snapshot()
    assert result["pose"] == state["pose"]
    assert result["conversation"] is None
    assert service.get("pending")["status"] == "accepted"
    assert backup.exists()
