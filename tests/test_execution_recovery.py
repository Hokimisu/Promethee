import copy
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from promethee.execution import ExecutionService
from promethee.runtime import Runtime
from promethee.world import ActionError


def submit(service, request_id="move"):
    return service.submit(
        request_id, service.get_world()["revision"], {"kind": "move", "args": {"position": [1, 0]}}
    )


def test_cancel_before_dispatch_has_no_body_effect(body):
    service, driver, _ = body
    before = service.get_world()
    submit(service)
    assert service.cancel("move")["status"] == "cancelled"
    events = service.events()
    assert service.cancel("move")["status"] == "cancelled"
    assert service.events() == events
    assert driver.handle.claim_next() is None
    assert service.get_world() == before


def test_cancel_waits_for_observed_acknowledgement_and_keeps_partial_position(body):
    service, driver, _ = body
    submit(service)
    driver.start()
    observation = copy.deepcopy(driver.observation)
    observation["avatar"]["position"] = [0.4, 0]
    assert driver.handle.feedback("move", 1, "running", observation=observation)
    assert service.cancel("move")["status"] == "running"
    assert driver.handle.claim_cancellation()["request_id"] == "move"
    assert driver.handle.claim_cancellation() is None
    assert driver.handle.feedback("move", 2, "cancelled", observation=observation)
    assert service.get_world()["avatar"]["position"] == [0.4, 0]
    assert service.get("move")["status"] == "cancelled"


def test_cancel_timeout_is_uncertain_and_cannot_be_extended_by_retries(body):
    service, driver, clock = body
    submit(service)
    driver.start()
    first = service.cancel("move")
    clock.advance(1)
    assert service.cancel("move")["cancel_deadline"] == first["cancel_deadline"]
    clock.advance(1)
    assert driver.handle.heartbeat()
    assert service.get("move")["status"] == "interrupted"
    assert service.get_world()["body"]["status"] == "unconfirmed"
    assert submit(service, "blocked")["error"]["code"] == "controller_unavailable"
    assert not driver.handle.feedback("move", 3, "completed", observation=driver.observation)
    with pytest.raises(ActionError, match="stopped"):
        driver.handle.reconcile(driver.observation, stopped=False)
    assert driver.handle.reconcile(driver.observation, stopped=True)
    assert service.get("move")["status"] == "interrupted"
    assert submit(service, "new-attempt")["status"] == "accepted"


def test_single_owner_and_stale_driver_fencing(body):
    service, driver, clock = body
    with pytest.raises(ActionError, match="already owns"):
        service.acquire_controller(source="logical-test", supported_actions=["move"])
    submit(service)
    driver.start()
    clock.advance(6)
    successor = service.acquire_controller(source="logical-test", supported_actions=["move"])
    assert service.get("move")["status"] == "interrupted"
    assert not driver.handle.heartbeat()
    assert not driver.handle.release()
    assert not driver.handle.feedback("move", 1, "completed", observation=driver.observation)
    assert not driver.handle.reconcile(driver.observation, stopped=True)
    assert successor.claim_next() is None
    assert successor.reconcile(driver.observation, stopped=True)
    assert submit(service, "successor")["status"] == "accepted"


def test_completion_and_cancellation_race_has_one_terminal_event(body):
    service, driver, _ = body
    submit(service)
    item = driver.start()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(service.cancel, "move"), pool.submit(driver.complete, item)]
        for future in futures:
            future.result()
    terminal = [event for event in service.events() if event["kind"] in {"completed", "cancelled"}]
    assert len(terminal) == 1
    assert service.get("move")["status"] == "completed"


@pytest.mark.parametrize("stage", ["accepted", "dispatched", "progress", "before_commit"])
def test_real_process_crash_never_reissues_an_uncertain_action(tmp_path, stage):
    path = tmp_path / "crash.sqlite3"
    script = """
import copy, json, os, sys
from promethee.runtime import Runtime
from promethee.execution import ExecutionService
runtime = Runtime(sys.argv[1])
service = ExecutionService(runtime, clock=lambda: 100)
driver = service.acquire_controller(
    source='logical-test', supported_actions=['move'], lease_seconds=1)
world = runtime.snapshot()
observation = {key: copy.deepcopy(world[key]) for key in ('avatar','objects')}
driver.reconcile(observation, stopped=True)
service.submit('move', service.get_world()['revision'], {'kind':'move','args':{'position':[1,0]}})
stage = sys.argv[2]
if stage != 'accepted':
    driver.claim_next()
if stage in ('progress','before_commit'):
    observation['avatar']['position'] = [0.4,0]
    driver.feedback('move', 0, 'running', observation=observation)
if stage == 'before_commit':
    with runtime.connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        world = runtime.snapshot()
        world['avatar']['position'] = [1,0]
        conn.execute('UPDATE world SET data=?', (json.dumps(world),))
        os._exit(0)
os._exit(0)
"""
    subprocess.run([sys.executable, "-c", script, str(path), stage], check=True)
    service = ExecutionService(Runtime(path), clock=lambda: 102)
    assert service.get("move")["status"] == "interrupted"
    world = service.get_world()
    assert world["avatar"]["position"] == (
        [0.4, 0] if stage in {"progress", "before_commit"} else [0, 0]
    )
    assert world["body"]["status"] == "unconfirmed"
    driver = service.acquire_controller(source="logical-test", supported_actions=["move"])
    assert driver.claim_next() is None
    observation = {key: world[key] for key in ("avatar", "objects")}
    assert driver.reconcile(observation, stopped=True)
    original = service.get("move")["envelope"]
    assert service.submit(**original)["status"] == "interrupted"
    assert driver.claim_next() is None
    assert submit(service, "new-attempt")["status"] == "accepted"
