"""Controlled-clock initiative budgets and provenance; no model inference."""

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from promethee.chat import TextHost
from promethee.conversation import ConversationStore
from promethee.execution import ExecutionService
from promethee.initiative import Initiative
from promethee.migrations import migrate, read_world
from promethee.runtime import Runtime, encode
from promethee.world import ActionError


def setup(tmp_path):
    clock = [100.0]
    runtime = Runtime(
        tmp_path / "world.sqlite3", data_origin="session", session_kind="qualification"
    )
    service = ExecutionService(runtime, clock=lambda: clock[0])
    return Initiative(service), ConversationStore(service), clock


def finish(store, opened):
    message = opened["message"]
    store.finish(
        opened["turn_id"],
        {
            "type": "result",
            "turn_id": opened["turn_id"],
            "text": "No action.",
            "failed": False,
            "interrupted": False,
            "messages": [
                *opened["history"],
                {"role": "user", "content": message},
                {"role": "assistant", "content": "No action."},
            ],
        },
    )


def test_disabled_default_no_initial_wake_and_exhausted_budget(tmp_path):
    initiative, store, clock = setup(tmp_path)
    assert initiative.observe() is None
    assert initiative.open_turn(store) is None
    initiative.configure(budget=2, interval=10)
    assert initiative.open_turn(store) is None
    for used in (1, 2):
        clock[0] += 10
        opened = initiative.open_turn(store)
        assert opened and "not a user message" in opened["message"]
        assert initiative.open_turn(store) is None
        finish(store, opened)
        state = initiative.observe()
        assert (state["used"], state["remaining"]) == (used, 2 - used)
        assert not state["pending"]["world_changed"]  # Own conversation writes do not wake it.
    clock[0] += 100
    assert initiative.open_turn(store) is None
    initiative.update(add_budget=1)
    assert initiative.open_turn(store) is not None


def test_slow_turn_coalesces_events_without_queueing_calls(tmp_path):
    initiative, store, clock = setup(tmp_path)
    initiative.configure(budget=3, interval=10)
    clock[0] += 10
    old = initiative.open_turn(store)
    service = store.service
    for i in range(20):
        service.submit(
            f"rejected-{i}",
            service.get_world()["revision"],
            {"kind": "move", "args": {"position": [0.2, 0.3]}},
        )
        clock[0] += 10
        initiative.observe()
        assert initiative.open_turn(store) is None
    state = initiative.observe()
    assert state["used"] == 1
    assert state["pending"]["terminal_count"] == 20
    assert len(state["pending"]["latest"]) == 8
    store.abort(old["turn_id"])
    opened = initiative.open_turn(store)
    assert '"terminal_count": 20' in opened["message"]
    finish(store, opened)
    assert initiative.open_turn(store) is None
    assert initiative.observe()["used"] == 2


def test_pause_persists_across_restart_and_fences_old_turn(tmp_path):
    initiative, store, clock = setup(tmp_path)
    initiative.configure(budget=3, interval=10)
    clock[0] += 10
    old = initiative.open_turn(store)
    initiative.update(paused=True)
    with pytest.raises(ActionError):
        store.service.end_turn(old["turn_id"])
    replacement = Initiative(
        ExecutionService(Runtime(store.service.runtime.path, create=False), clock=lambda: clock[0])
    )
    clock[0] += 100
    assert replacement.observe()["paused"]
    assert replacement.open_turn(store) is None
    replacement.update(paused=False)
    assert replacement.open_turn(store) is None  # No cadence debt after a pause.
    clock[0] += 10
    new = replacement.open_turn(store)
    assert new["turn_id"] != old["turn_id"]
    assert replacement.observe()["used"] == 2


def test_reservation_and_turn_rollback_together(tmp_path):
    initiative, store, clock = setup(tmp_path)
    initiative.configure(budget=1, interval=1)
    clock[0] += 1
    before = store.service.runtime.snapshot()
    with store.service.runtime.connection() as conn:
        conn.execute(
            "CREATE TRIGGER fail_turn BEFORE INSERT ON conversation_turns "
            "BEGIN SELECT RAISE(ABORT, 'qualification rollback'); END;"
        )
    with pytest.raises(sqlite3.IntegrityError, match="qualification rollback"):
        initiative.open_turn(store)
    assert store.service.runtime.snapshot() == before
    with store.service.runtime.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM conversation_turns").fetchone()[0] == 0


def test_concurrent_reservations_create_only_one_turn_and_pause_is_idempotent(tmp_path):
    initiative, store, clock = setup(tmp_path)
    initiative.configure(budget=2, interval=1)
    clock[0] += 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(initiative.open_turn, store) for _ in range(2)]
        results = [future.result() for future in futures]
    assert sum(result is not None for result in results) == 1
    assert initiative.observe()["used"] == 1
    initiative.update(paused=True)
    paused = store.service.runtime.snapshot()
    initiative.update(paused=True)
    assert store.service.runtime.snapshot() == paused


def test_claim_is_not_replayed_after_crash_and_user_correction_wins(tmp_path):
    initiative, store, clock = setup(tmp_path)
    initiative.configure(budget=2, interval=10)
    clock[0] += 10
    old = initiative.open_turn(store)
    replacement = ConversationStore(store.service)
    replacement.recover()
    assert initiative.open_turn(replacement) is None
    assert initiative.observe()["used"] == 1
    user = replacement.begin("A real user correction")
    clock[0] += 10
    assert initiative.open_turn(replacement) is None
    initiative.update(paused=True)
    assert store.service.get_world()["conversation"]["turn_id"] == user["turn_id"]
    with pytest.raises(ActionError):
        store.service.end_turn(old["turn_id"])


def test_capability_removal_wakes_once_and_pause_does_not_cancel_body(tmp_path, articulated_pose):
    initiative, store, _ = setup(tmp_path)
    service = store.service
    driver = service.acquire_controller(source="kinematic", supported_actions=["move"])
    world = service.runtime.snapshot()
    observation = {k: copy.deepcopy(world[k]) for k in ("avatar", "objects")}
    observation["pose"] = articulated_pose
    driver.reconcile(observation, stopped=True)
    initiative.configure(budget=2)
    service.submit(
        "move", service.get_world()["revision"], {"kind": "move", "args": {"position": [0.2, 0.3]}}
    )
    before = service.get("move")
    initiative.update(paused=True)
    assert service.get("move") == before
    driver.release()
    initiative.observe()
    initiative.update(paused=False)
    opened = initiative.open_turn(store)
    assert opened and service.supported_actions() == []
    assert initiative.observe()["pending"]["latest"] == []
    finish(store, opened)
    assert initiative.open_turn(store) is None


def test_fixture_refused_and_invalid_budgets_do_not_enable(tmp_path):
    with pytest.raises(ActionError):
        Initiative(ExecutionService(Runtime(tmp_path / "fixture.sqlite3")))
    initiative, store, _ = setup(tmp_path)
    for budget in (0, -1, True, 1.5, 1001):
        with pytest.raises(ValueError):
            initiative.configure(budget=budget)
    assert store.service.runtime.snapshot()["initiative"] is None


def test_runtime_wake_never_becomes_a_user_memory_source(tmp_path):
    pytest.importorskip("yaml")
    from promethee.memory import MemoryStore, initialize_vault

    # Deliberate fixture of the interactive contract, isolated in pytest's fresh directory.
    runtime = Runtime(tmp_path / "world.sqlite3", data_origin="session", session_kind="interactive")
    clock = [100.0]
    service = ExecutionService(runtime, clock=lambda: clock[0])
    initiative, store = Initiative(service), ConversationStore(service)
    memory = MemoryStore(service, initialize_vault(runtime, tmp_path / "vault"))
    initiative.configure(budget=1, interval=1)
    clock[0] += 1
    opened = initiative.open_turn(store)
    with pytest.raises(ActionError, match="not a user"):
        memory.source("user:" + opened["turn_id"])
    source = "runtime:" + opened["turn_id"]
    assert memory.source(source)["kind"] == "runtime"
    memory.write(
        "proposal", kind="proposal", title="Test", text="Possible intention", sources=[source]
    )
    with pytest.raises(ActionError, match="cannot attest"):
        memory.write(
            "observation", kind="observation", title="Test", text="Claim", sources=[source]
        )


@pytest.mark.parametrize("fail", [False, True])
def test_v7_migration_preserves_world_and_does_not_enable_initiative(tmp_path, fail):
    _, store, _ = setup(tmp_path)
    runtime = store.service.runtime
    with runtime.connection() as conn:
        world = read_world(conn)
        world["schema_version"] = 7
        world.pop("initiative")
        conn.execute("UPDATE world SET data=? WHERE id=1", (encode(world),))
        if fail:
            conn.execute(
                "CREATE TRIGGER fail_v8 BEFORE UPDATE ON world "
                "BEGIN SELECT RAISE(ABORT, 'v8 rollback'); END;"
            )
        before = list(conn.iterdump())
    backup = tmp_path / "v7-backup.sqlite3"
    if fail:
        with pytest.raises(sqlite3.IntegrityError):
            migrate(runtime.path, backup)
        with runtime.connection() as conn:
            assert list(conn.iterdump()) == before
    else:
        migrate(runtime.path, backup)
        updated = runtime.snapshot()
        assert updated.pop("initiative") is None
        updated["schema_version"] = 7
        assert updated == world
    with sqlite3.connect(backup) as conn:
        assert list(conn.iterdump()) == before


def test_host_closes_paused_initiative_and_keeps_user_turn(tmp_path):
    initiative, store, clock = setup(tmp_path)
    workers = []

    class Worker:
        closed = False

        def __init__(self, request):
            self.request = request
            workers.append(self)

        def close(self):
            self.closed = True

        def poll(self):
            return None

    host = TextHost(store, Worker, model="fixture", base_url="unused", api_mode="chat_completions")
    initiative.configure(budget=2, interval=1)
    clock[0] += 1
    assert host.initiative_tick()["started"] == workers[0].request["turn_id"]
    initiative.update(paused=True)
    assert host.initiative_tick() == {"paused": True}
    assert workers[0].closed
    host.start("User message")
    host.initiative_tick()
    assert not workers[1].closed
    with store.service.runtime.connection() as conn:
        records = [json.loads(r[0]) for r in conn.execute("SELECT data FROM conversation_turns")]
    assert [r["trigger"] for r in records] == ["initiative", "user"]
    host.close()
