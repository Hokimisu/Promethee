"""Reserved turns and disposable preparation, using real local processes, no model."""

import json
import sqlite3
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_chat_host import alive

from promethee.chat import TextHost, WorkerProcess, open_text_host, prepare_profile
from promethee.conversation import ConversationStore
from promethee.execution import ExecutionService
from promethee.hermes_adapter import CODEX_BASE_URL, WORLD_TOOLS
from promethee.runtime import Runtime, encode
from promethee.world import ActionError


def until(callback, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = callback()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("Local fixture did not finish before its deadline.")


def make_store(tmp_path):
    return ConversationStore(
        ExecutionService(Runtime(tmp_path / "world.sqlite3", data_origin="session"))
    )


def result(turn, message):
    return {
        "type": "result",
        "turn_id": turn["turn_id"],
        "failed": False,
        "interrupted": False,
        "text": "Fixture",
        "messages": [
            *turn["history"],
            {"role": "user", "content": message},
            {"role": "assistant", "content": "Fixture"},
        ],
    }


def test_reservation_is_invisible_until_atomic_activation_and_history_is_fresh(tmp_path):
    store = make_store(tmp_path)
    before = store.service.get_world()
    reservation = store.reserve_turn()
    assert store.service.get_world() == before
    assert store.context()["messages"] == []
    with store.service.runtime.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM conversation_turns").fetchone()[0] == 0
        with pytest.raises(ActionError):
            store.service._check_turn(conn, reservation.turn_id, time.time())
    previous = store.begin("Just arrived")
    store.finish(previous["turn_id"], result(previous, "Just arrived"))
    opened = store.begin("Next", reservation=reservation)
    assert opened["turn_id"] == reservation.turn_id
    assert opened["history"][-1] == {"role": "assistant", "content": "Fixture"}
    with pytest.raises(ValueError):
        store.begin("Reuse", reservation=reservation)


def test_reservation_refuses_foreign_forged_expired_and_recovered_handles(tmp_path):
    store = make_store(tmp_path)
    reserved = store.reserve_turn()
    with pytest.raises(ValueError, match="one"):
        store.reserve_turn()
    with pytest.raises(ValueError, match="belong"):
        store.begin("Forged", reservation=replace(reserved, turn_id="turn-forged"))
    other = ConversationStore(store.service)
    with pytest.raises(ValueError, match="belong"):
        other.begin("Foreign", reservation=reserved)
    original_clock = store.service.clock
    store.service.clock = lambda: reserved.expires_at
    with pytest.raises(ValueError, match="expired"):
        store.begin("Expired", reservation=reserved)
    store.service.clock = original_clock
    store.recover()
    with pytest.raises(ValueError, match="belong"):
        store.begin("Recovered", reservation=reserved)


def test_reserved_activation_rolls_back_and_can_be_retried(tmp_path):
    store = make_store(tmp_path)
    reserved = store.reserve_turn()
    with store.service.runtime.connection() as conn:
        conn.execute("""CREATE TRIGGER fail_turn BEFORE UPDATE ON world
            BEGIN SELECT RAISE(ABORT, 'rollback'); END;""")
        before = list(conn.iterdump())
    with pytest.raises(sqlite3.IntegrityError):
        store.begin("Input", reservation=reserved)
    with store.service.runtime.connection() as conn:
        assert list(conn.iterdump()) == before
        conn.execute("DROP TRIGGER fail_turn")
    assert store.begin("Input", reservation=reserved)["turn_id"] == reserved.turn_id


def test_reserved_activation_checks_session_and_existing_id(tmp_path):
    store = make_store(tmp_path)
    reserved = store.reserve_turn()
    with store.service.runtime.connection() as conn:
        world = store.service.get_world()
        world["world_id"] = "different-session"
        conn.execute("UPDATE world SET data=? WHERE id=1", (encode(world),))
    with pytest.raises(ValueError, match="session"):
        store.begin("Wrong session", reservation=reserved)
    with store.service.runtime.connection() as conn:
        world["world_id"] = reserved.session_id
        conn.execute("UPDATE world SET data=? WHERE id=1", (encode(world),))
        conn.execute(
            "INSERT INTO conversation_turns(turn_id,status,data) VALUES (?,?,?)",
            (reserved.turn_id, "context", encode({"message": "Existing"})),
        )
    with pytest.raises(ValueError, match="used"):
        store.begin("Duplicate", reservation=reserved)


def fake_hermes(tmp_path, *, delay=0, changed_auth=False, child=False, result_flags=None):
    root = tmp_path / "hermes"
    root.mkdir()
    child_code = (
        "  import subprocess,sys\n"
        "  child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
        "  Path(__file__).with_name('child.pid').write_text(str(child.pid))\n"
        if child
        else ""
    )
    (root / "run_agent.py").write_text(
        "import json,time\nfrom pathlib import Path\n"
        "class AIAgent:\n"
        " def __init__(self, **kw):\n"
        f"  time.sleep({delay!r})\n"
        "  self.model=kw['model']; self.provider=kw['provider']; self.api_mode=kw['api_mode']\n"
        f"  self.valid_tool_names={sorted(WORLD_TOOLS)!r}; self._fallback_chain=[]\n"
        "  Path(__file__).with_name('constructed').touch()\n"
        + child_code
        + " def run_conversation(self,message,conversation_history,task_id,system_message=None):\n"
        "  Path(__file__).with_name('called.json').write_text(json.dumps(\n"
        "   {'message':message,'history':conversation_history,'system_message':system_message}))\n"
        "  return {'final_response':'Fixture','messages':[*conversation_history,\n"
        "   {'role':'user','content':message},{'role':'assistant','content':'Fixture'}],"
        f"**{result_flags or {}!r}}}\n"
    )
    (root / "tools").mkdir()
    (root / "tools/__init__.py").write_text("")
    (root / "tools/mcp_tool.py").write_text(
        f"def discover_mcp_tools(): return {sorted(WORLD_TOOLS)!r}\n"
        "def shutdown_mcp_servers(): pass\n"
    )
    (root / "hermes_cli").mkdir()
    (root / "hermes_cli/__init__.py").write_text("")
    (root / "hermes_cli/runtime_provider.py").write_text(
        "calls=0\ndef resolve_runtime_provider(**kw):\n"
        " global calls\n calls+=1\n"
        f" key='fixture-key-new' if {changed_auth!r} and calls>1 else 'fixture-key'\n"
        f" return {{'provider':'openai-codex','api_mode':'codex_responses',"
        f"'base_url':{CODEX_BASE_URL!r},'api_key':key}}\n"
    )
    return root


def host_args(tmp_path, root):
    Runtime(tmp_path / "world.sqlite3", data_origin="session")
    return SimpleNamespace(
        data_dir=tmp_path,
        hermes_python=Path(sys.executable),
        hermes_root=root,
        hermes_auth_root=tmp_path,
        auth="hermes-codex",
        model="fixture",
        api_mode="codex_responses",
        base_url=None,
        vault=None,
        timeout=5,
        prewarm=True,
        measure_timing=True,
        reasoning_effort="low",
        system_message="Stable persona",
    )


def test_ready_worker_has_no_model_call_then_uses_fresh_history_and_system_message(tmp_path):
    root = fake_hermes(tmp_path)
    with open_text_host(host_args(tmp_path, root)) as host:
        until(lambda: host.warm_status()["state"] == "ready")
        assert (root / "constructed").exists()
        assert not (root / "called.json").exists()
        assert host.store.service.get_world()["conversation"] is None
        spare = host.spare
        previous = host.store.begin("Earlier")
        host.store.finish(previous["turn_id"], result(previous, "Earlier"))
        seen = []
        host.worker_wrapper = lambda worker, request: seen.append(request) or worker
        host.start("Fresh message")
        assert host.worker is spare and host.spare is None
        response = until(host.poll)
        assert response["status"] == "completed"
        call = json.loads((root / "called.json").read_text())
        assert call["system_message"] == "Stable persona"
        assert call["message"] == "Fresh message"
        assert call["history"][-1]["content"] == "Fixture"
        assert "Stable persona" not in json.dumps(host.store.context())
        assert seen[0]["message"] == "Fresh message"
        assert response["timings"]["prewarm_seconds"] >= 0
        assert response["timings"]["activation_seconds"] >= 0
        assert spare.process.poll() is not None


def test_partly_prepared_worker_is_adopted_without_cold_restart(tmp_path):
    root = fake_hermes(tmp_path, delay=0.2)
    with open_text_host(host_args(tmp_path, root)) as host:
        spare = host.spare
        assert host.warm_status()["state"] == "preparing"
        host.factory = lambda request: pytest.fail("A preparing spare must not be discarded")
        host.start("Immediate input")
        assert host.worker is spare
        assert until(host.poll)["status"] == "completed"


def test_cold_worker_also_passes_system_message_without_transcript_pollution(tmp_path):
    root = fake_hermes(tmp_path)
    args = host_args(tmp_path, root)
    args.prewarm = False
    with open_text_host(args) as host:
        assert host.warm_status()["state"] == "disabled"
        host.start("Only user message")
        assert until(host.poll)["status"] == "completed"
        call = json.loads((root / "called.json").read_text())
        assert call["system_message"] == "Stable persona"
        assert host.store.context()["messages"][0]["content"] == "Only user message"
        assert "Stable persona" not in json.dumps(host.store.context())


@pytest.mark.parametrize("prewarm", [False, True], ids=["cold", "prewarm"])
@pytest.mark.parametrize(
    "flags,failed",
    [
        pytest.param({}, False, id="legacy-success"),
        pytest.param(
            {"failed": False, "partial": False, "completed": True}, False, id="native-success"
        ),
        pytest.param({"error": "Fixture failure"}, True, id="error"),
        pytest.param({"failed": True}, True, id="native-failed"),
        pytest.param({"partial": True}, True, id="native-partial"),
        pytest.param({"completed": False}, True, id="native-incomplete"),
    ],
)
def test_cold_and_prewarm_preserve_native_failure_flags(tmp_path, prewarm, flags, failed):
    root = fake_hermes(tmp_path, result_flags=flags)
    args = host_args(tmp_path, root)
    args.prewarm = prewarm
    with open_text_host(args) as host:
        if prewarm:
            until(lambda: host.warm_status()["state"] == "ready")
        host.start("Neutral fixture")
        worker = host.worker
        response = until(host.poll)
        assert response["status"] == ("failed" if failed else "completed")
        expected = [{"role": "user", "content": "Neutral fixture"}]
        if not failed:
            expected.append({"role": "assistant", "content": "Fixture"})
        assert host.store.context()["messages"] == expected
        assert host.store.service.get_world()["conversation"] is None
        assert worker.process.poll() is not None


def test_cancel_during_preparation_fences_before_stopping_and_retains_user(tmp_path):
    root = fake_hermes(tmp_path, delay=2)
    with open_text_host(host_args(tmp_path, root)) as host:
        spare = host.spare
        host.start("Keep this correction")
        close = spare.close

        def fenced_close():
            assert host.store.service.get_world()["conversation"] is None
            close()

        spare.close = fenced_close
        host.cancel()
        assert spare.process.poll() is not None
        assert not (root / "called.json").exists()
        assert host.store.context()["messages"] == [
            {"role": "user", "content": "Keep this correction"}
        ]


@pytest.mark.parametrize("expiry", [False, True])
def test_discard_prepared_worker_stops_its_child_processes(tmp_path, expiry):
    root = fake_hermes(tmp_path, child=True)
    with open_text_host(host_args(tmp_path, root)) as host:
        if expiry:
            host.close()
            host.prewarm_lifetime = 1
            host.warm()
        spare = host.spare
        until(lambda: host.warm_status()["state"] == "ready")
        pid = int((root / "child.pid").read_text())
        assert alive(pid)
        if expiry:
            until(lambda: spare.closed)
        else:
            host.close()
        until(lambda: not alive(pid))
        assert not (root / "called.json").exists()


def test_expiry_between_status_and_begin_falls_back_before_input_is_persisted(tmp_path):
    root = fake_hermes(tmp_path)
    with open_text_host(host_args(tmp_path, root)) as host:
        spare = host.spare
        original_begin = host.store.begin
        clock = host.store.service.clock

        def racing_begin(message, **options):
            reservation = options.get("reservation")
            if reservation:
                host.store.service.clock = lambda: reservation.expires_at
            try:
                return original_begin(message, **options)
            finally:
                host.store.service.clock = clock

        host.store.begin = racing_begin
        host.start("One input")
        assert host.worker is not spare
        assert until(host.poll)["status"] == "completed"
        assert host.store.context()["messages"][0]["content"] == "One input"
        assert len(host.store.context()["messages"]) == 2


@pytest.mark.parametrize("cancel", [False, True])
def test_unavailable_prepared_worker_after_begin_returns_once_without_retry(tmp_path, cancel):
    root = fake_hermes(tmp_path)
    with open_text_host(host_args(tmp_path, root)) as host:

        def expired(request):
            raise ValueError("Prepared process expired between begin and activation")

        host.spare.activate = expired
        host.factory = lambda request: pytest.fail("Do not reuse the prepared profile")
        host.start("Retained unanswered input")
        assert host.store.service.get_world()["conversation"] is None
        if cancel:
            host.cancel()
            assert host.poll() is None
        else:
            assert host.poll()["code"] == "prepared_worker_unavailable"
            assert host.poll() is None
        assert host.store.context()["messages"] == [
            {"role": "user", "content": "Retained unanswered input"}
        ]


def test_cancel_preserves_spare_close_discards_it_and_expiry_is_bounded(tmp_path):
    root = fake_hermes(tmp_path)
    with open_text_host(host_args(tmp_path, root)) as host:
        spare = host.spare
        reserved = host.reservation
        host.cancel()
        assert host.spare is spare and host.reservation is reserved
        host.close()
        assert spare.process.poll() is not None
        assert host.spare is None and host.warm_status()["state"] == "idle"
        host.prewarm_lifetime = 0.15
        factory = host.prewarm_factory
        created = []

        def capture_worker(request):
            worker = factory(request)
            created.append(worker)
            return worker

        host.prewarm_factory = capture_worker
        host.warm()
        # A slow process launch may expire before warm() returns and clears spare.
        # Keep the created worker to verify its actual cleanup in either ordering.
        assert len(created) == 1
        expired = created[0]
        until(lambda: expired.closed)
        assert host.warm_status()["state"] == "expired"
        assert expired.process.poll() is not None
        assert host.store.service.get_world()["conversation"] is None
        assert not (root / "called.json").exists()


def test_auth_changed_since_preparation_is_refused_before_model_call(tmp_path):
    root = fake_hermes(tmp_path, changed_auth=True)
    with open_text_host(host_args(tmp_path, root)) as host:
        until(lambda: host.warm_status()["state"] == "ready")
        host.start("User input")
        assert until(host.poll)["status"] == "failed"
        assert not (root / "called.json").exists()
        assert host.store.context()["messages"] == [{"role": "user", "content": "User input"}]


@pytest.mark.parametrize("change", ["unactivated", "settings", "profile"])
def test_worker_independently_rejects_unactivated_or_changed_request(tmp_path, change):
    root = fake_hermes(tmp_path)
    store = make_store(tmp_path)
    reserved = store.reserve_turn()
    profile = tmp_path / "profiles/fixture"
    prepare_profile(profile, tmp_path, reserved.turn_id)
    setup = {
        "turn_id": reserved.turn_id,
        "session_id": reserved.session_id,
        "model": "fixture",
        "base_url": CODEX_BASE_URL,
        "api_mode": "codex_responses",
        "standby_seconds": 5,
    }
    command = [
        sys.executable,
        str(Path(__file__).parents[1] / "src/promethee/hermes_worker.py"),
        "--hermes-root",
        str(root),
        "--profile",
        str(profile),
        "--auth",
        "hermes-codex",
        "--prewarm",
    ]
    worker = WorkerProcess(command, setup, prewarm=True, lifetime=5)
    try:
        until(lambda: worker.warm_status()["state"] == "ready")
        request = {k: v for k, v in setup.items() if k != "standby_seconds"}
        request.update(message="Input", history=[])
        if change != "unactivated":
            store.begin("Input", reservation=reserved)
        if change == "settings":
            request["model"] = "other"
            with pytest.raises(ValueError):
                worker.activate(request)
            return
        if change == "profile":
            (profile / "config.yaml").write_text("{}")
        worker.activate(request)
        response = until(worker.poll)
        assert response["type"] == "error"
        assert not (root / "called.json").exists()
    finally:
        worker.close()


@pytest.mark.parametrize("system_message", ["", " ", 1, False, [], "x" * 16001])
def test_invalid_system_message_rejected_before_any_conversation(tmp_path, system_message):
    store = make_store(tmp_path)
    with pytest.raises(ValueError, match="system message"):
        TextHost(
            store,
            lambda request: None,
            model="fixture",
            base_url="unused",
            api_mode="chat_completions",
            system_message=system_message,
        )
    assert store.service.get_world()["conversation"] is None
