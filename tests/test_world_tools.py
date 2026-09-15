import copy
import sqlite3

import pytest

from promethee.execution import ExecutionService
from promethee.mcp_server import WorldTools
from promethee.runtime import Runtime
from promethee.world import ActionError


def session_tools(tmp_path, articulated_pose):
    runtime = Runtime(tmp_path / "world.sqlite3", data_origin="session")
    service = ExecutionService(runtime)
    # Contract-only CPU test driver, not a real ARDY qualification.
    handle = service.acquire_controller(source="kinematic", supported_actions=["move"])
    state = runtime.snapshot()
    observation = {key: copy.deepcopy(state[key]) for key in ("avatar", "objects")}
    observation["pose"] = articulated_pose
    handle.reconcile(observation, stopped=True)
    return WorldTools(service), handle


def test_tools_preserve_submission_idempotence_and_never_teleport(tmp_path, articulated_pose):
    tools, handle = session_tools(tmp_path, articulated_pose)
    before = tools.world()
    assert tools.capabilities()["actions"] == [{"kind": "move", "required_args": ["position"]}]
    action = {"kind": "move", "args": {"position": [0.3, 0.2]}}
    assert tools.submit("move-one", before["revision"], action)["status"] == "accepted"
    assert tools.submit("move-one", before["revision"], action)["replayed"]
    current = tools.world()
    assert {k: v for k, v in current.items() if k != "recent_executions"} == {
        k: v for k, v in before.items() if k != "recent_executions"
    }
    assert current["recent_executions"]["items"][0]["status"] == "accepted"
    assert tools.execution("move-one")["status"] == "accepted"
    assert tools.cancel("move-one")["status"] == "cancelled"
    assert tools.cancel("move-one")["status"] == "cancelled"
    assert handle.claim_next() is None
    with pytest.raises(ActionError, match="different envelope"):
        tools.submit("move-one", before["revision"] + 1, action)


def test_tools_cannot_reconcile_a_missing_controller(tmp_path, articulated_pose):
    tools, handle = session_tools(tmp_path, articulated_pose)
    handle.release()
    world = tools.world()
    assert world["body"]["status"] == "unconfirmed"
    assert tools.capabilities()["actions"] == []
    result = tools.submit(
        "attempt", world["revision"], {"kind": "move", "args": {"position": [0, 0]}}
    )
    assert result["error"]["code"] == "controller_unavailable"


def test_tools_refuse_fixture_world(tmp_path):
    runtime = Runtime(tmp_path / "fixture.sqlite3")
    with pytest.raises(ActionError, match="session world"):
        WorldTools(ExecutionService(runtime))


def test_new_turn_finds_cancelled_request_without_old_agent_history(tmp_path, articulated_pose):
    tools, _ = session_tools(tmp_path, articulated_pose)
    service = tools.service
    old = WorldTools(service, turn_id=service.begin_turn())
    old.submit(
        "interrupted-request",
        old.world()["revision"],
        {"kind": "move", "args": {"position": [0.3, 0.2]}},
    )
    current = WorldTools(service, turn_id=service.begin_turn())
    service.cancel("interrupted-request")
    before, events = service.runtime.snapshot(), service.events()
    receipt = current.world()["recent_executions"]["items"][0]
    assert receipt["request_id"] == "interrupted-request"
    assert receipt["status"] == "cancelled" and receipt["cancel_requested"]
    assert receipt["action"] == {"kind": "move", "args": {"position": [0.3, 0.2]}}
    assert "observation" not in receipt
    assert current.execution(receipt["request_id"])["status"] == "cancelled"
    assert service.runtime.snapshot() == before and service.events() == events
    assert "recent_executions" not in before
    other = WorldTools(ExecutionService(Runtime(tmp_path / "other.sqlite3", data_origin="session")))
    assert other.world()["recent_executions"] == {"items": [], "has_more": False}


def test_receipts_are_bounded_and_include_latest_update_of_an_older_action(
    tmp_path, articulated_pose
):
    tools, _ = session_tools(tmp_path, articulated_pose)
    action = {"kind": "move", "args": {"position": [0.1, 0.2]}}
    tools.submit("pending", tools.world()["revision"], action)
    for index in range(10):
        tools.submit(f"rejected-{index}", 0, action)
    tools.cancel("pending")
    receipts = tools.world()["recent_executions"]
    assert len(receipts["items"]) == 8 and receipts["has_more"]
    assert receipts["items"][0]["request_id"] == "pending"
    assert receipts["items"][0]["status"] == "cancelled"


def test_receipts_and_body_reflect_controller_expiry_together(tmp_path, articulated_pose):
    tools, _ = session_tools(tmp_path, articulated_pose)
    service = tools.service
    tools.submit(
        "lost-controller",
        tools.world()["revision"],
        {"kind": "move", "args": {"position": [0.1, 0.2]}},
    )
    expired = service.clock() + 6
    service.clock = lambda: expired
    world = tools.world()
    assert world["body"]["status"] == "unconfirmed"
    assert world["recent_executions"]["items"][0]["status"] == "interrupted"
    assert world["recent_executions"]["items"][0]["error"]["code"] == "controller_lost"


def test_existing_mode_never_creates_or_initializes_a_world(tmp_path):
    absent = tmp_path / "absent" / "world.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        Runtime(absent, create=False)
    assert not absent.parent.exists()
    empty = tmp_path / "empty.sqlite3"
    empty.touch()
    with pytest.raises(ValueError, match="does not contain"):
        Runtime(empty, create=False)
    with sqlite3.connect(empty) as conn:
        assert conn.execute("SELECT name FROM sqlite_master").fetchall() == []
