import copy
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from promethee.execution import ExecutionService
from promethee.runtime import Runtime
from promethee.world import ActionError


def move(position):
    return {"kind": "move", "args": {"position": position}}


def test_submission_waits_for_observed_completion_and_replay_returns_latest_state(body):
    service, driver, _ = body
    before = service.get_world()
    request = service.submit("move", before["revision"], move([2, 0]))
    assert request["status"] == "accepted"
    assert service.get_world() == before
    item = driver.start()
    assert service.get("move")["status"] == "running"
    assert service.get_world()["avatar"] == before["avatar"]
    assert driver.complete(item)
    assert service.get("move")["status"] == "completed"
    assert service.get_world()["avatar"]["position"] == [2, 0]
    events = service.events()
    replay = service.submit("move", before["revision"], move([2, 0]))
    assert replay["replayed"] and replay["status"] == "completed"
    assert service.events() == events
    assert driver.handle.claim_next() is None
    with pytest.raises(ActionError, match="different envelope"):
        service.submit("move", service.get_world()["revision"], move([2, 0]))


def test_concurrent_retransmissions_create_one_execution(body):
    service, _, _ = body
    revision = service.get_world()["revision"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.submit("move", revision, move([1, 0])), range(4)))
    assert sum(not result["replayed"] for result in results) == 1
    assert len(service.events()) == 1


def test_rejections_are_durable_and_do_not_mutate_the_world(body):
    service, driver, _ = body
    before = service.get_world()
    assert (
        service.submit("stale", before["revision"] - 1, move([1, 0]))["error"]["code"]
        == "revision_conflict"
    )
    assert service.submit("invalid", before["revision"], move([20, 0]))["status"] == "rejected"
    assert service.submit("invalid", before["revision"], move([20, 0]))["replayed"]
    assert service.get_world() == before
    service.submit("move", before["revision"], move([1, 0]))
    assert service.submit("busy", before["revision"], move([2, 0]))["error"]["code"] == "busy"
    with pytest.raises(ActionError, match="busy"):
        service.runtime.execute("shortcut", move([3, 0]))
    assert driver.handle.claim_next()["request_id"] == "move"
    assert driver.handle.claim_next() is None


def test_feedback_cannot_precede_dispatch_or_invent_a_terminal_state(body):
    service, driver, _ = body
    service.submit("move", service.get_world()["revision"], move([1, 0]))
    with pytest.raises(ActionError, match="dispatch"):
        driver.handle.feedback("move", 0, "running")
    driver.handle.claim_next()
    with pytest.raises(ActionError, match="running"):
        driver.handle.feedback("move", 0, "completed", observation=driver.observation)
    driver.handle.feedback("move", 0, "running")
    with pytest.raises(ActionError, match="full observed"):
        driver.handle.feedback("move", 1, "completed")
    assert service.get("move")["status"] == "running"


def test_repeated_and_out_of_order_feedback_has_no_effect(body):
    service, driver, _ = body
    service.submit("move", service.get_world()["revision"], move([1, 0]))
    item = driver.start()
    assert driver.handle.feedback("move", 4, "running", observation=driver.observation)
    before = service.events()
    assert not driver.handle.feedback("move", 4, "running", observation=driver.observation)
    assert not driver.handle.feedback("move", 3, "failed", error="late failure")
    assert service.events() == before
    assert driver.complete(item, sequence=5)
    assert not driver.handle.feedback("move", 6, "failed", error="after completion")
    assert service.get("move")["status"] == "completed"


@pytest.mark.parametrize("invalid", ["metadata", "nonfinite", "detached"])
def test_invalid_observations_do_not_advance_world_or_execution(body, invalid):
    service, driver, _ = body
    service.submit("move", service.get_world()["revision"], move([1, 0]))
    driver.start()
    observation = copy.deepcopy(driver.observation)
    if invalid == "metadata":
        observation["data_origin"] = "session"
    elif invalid == "nonfinite":
        observation["avatar"]["position"] = [float("nan"), 0]
    else:
        observation["avatar"]["holding"] = "missing"
    before = service.get_world(), service.events()
    with pytest.raises(ActionError):
        driver.handle.feedback("move", 1, "completed", observation=observation)
    assert (service.get_world(), service.events()) == before


def test_world_outcome_and_event_commit_or_roll_back_together(body):
    service, driver, _ = body
    service.submit("move", service.get_world()["revision"], move([1, 0]))
    item = driver.start()
    before = service.get_world(), service.get("move"), service.events()
    with service.runtime.connection() as conn:
        conn.execute("""CREATE TRIGGER fail_outcome BEFORE INSERT ON execution_events
            BEGIN SELECT RAISE(ABORT, 'simulated event write failure'); END;""")
    with pytest.raises(sqlite3.IntegrityError, match="simulated event write failure"):
        driver.complete(item)
    assert (service.get_world(), service.get("move"), service.events()) == before
    with service.runtime.connection() as conn:
        conn.execute("DROP TRIGGER fail_outcome")
    assert driver.complete(item)


def test_controller_source_and_capabilities_are_explicit(tmp_path):
    runtime = Runtime(tmp_path / "session.sqlite3", data_origin="session")
    service = ExecutionService(runtime)
    with pytest.raises(ActionError, match="fixture"):
        service.acquire_controller(source="logical-test", supported_actions=["move"])
    handle = service.acquire_controller(source="kinematic", supported_actions=["move"])
    world = service.get_world()
    assert service.submit("unconfirmed", world["revision"], move([1, 0]))["status"] == "rejected"
    handle.reconcile({key: world[key] for key in ("avatar", "objects")}, stopped=True)
    unsupported = {
        "kind": "spawn",
        "args": {"object_id": "x", "asset": "plush", "position": [0, 0]},
    }
    assert (
        service.submit("unsupported", service.get_world()["revision"], unsupported)["status"]
        == "rejected"
    )
    assert service.supported_actions() == ["move"]


def test_failed_execution_preserves_cause_and_requires_reconciliation(body):
    service, driver, _ = body
    service.submit("move", service.get_world()["revision"], move([1, 0]))
    driver.start()
    assert driver.handle.feedback("move", 1, "failed", error="target became inaccessible")
    assert service.get("move")["error"]["code"] == "controller_failure"
    assert service.get_world()["body"]["status"] == "unconfirmed"
    assert (
        service.submit("next", service.get_world()["revision"], move([1, 0]))["status"]
        == "rejected"
    )
