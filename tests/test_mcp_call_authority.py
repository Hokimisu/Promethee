"""Real stdio authority tests, with synthetic CPU observations and no model."""

import asyncio
import json
import subprocess
import sys
from contextlib import asynccontextmanager
from time import monotonic
from uuid import uuid4

import pytest

pytest.importorskip("mcp")

from mcp.client.session import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402
from test_appearance_checkpoint import observed  # noqa: E402

from promethee.conversation import ConversationStore  # noqa: E402
from promethee.execution import ExecutionService  # noqa: E402
from promethee.mcp_server import create_server  # noqa: E402
from promethee.runtime import Runtime  # noqa: E402

AUTHORITY = "_promethee_turn_id"


@asynccontextmanager
async def connect(directory, *, vault=None, entered=None):
    args = ["-m", "promethee.mcp_server", "--data-dir", str(directory), "--call-authority"]
    if vault is not None:
        args += ["--vault", str(vault)]
    if entered is not None:
        # Only this CPU test seam signals admission to submit, before its SQLite
        # transaction waits on the host lock. The transport/server are real.
        script = """from pathlib import Path
import sys
from promethee.execution import ExecutionService
from promethee.runtime import Runtime
from promethee.mcp_server import create_server
class ObservedService(ExecutionService):
    def submit(self,*args,**kwargs):
        Path(sys.argv[2]).touch()
        return super().submit(*args,**kwargs)
service=ObservedService(Runtime(Path(sys.argv[1])/'world.sqlite3',create=False))
create_server(service,call_authority=True).run(transport='stdio')
"""
        args = ["-c", script, str(directory), str(entered)]
    params = StdioServerParameters(command=sys.executable, args=args)
    async with stdio_client(params) as streams, ClientSession(*streams) as client:
        await client.initialize()
        yield client


@pytest.fixture
def body(tmp_path, articulated_pose):
    runtime = Runtime(
        tmp_path / "world.sqlite3", data_origin="session", session_kind="qualification"
    )
    service = ExecutionService(runtime)
    handle = service.acquire_controller(
        source="kinematic", supported_actions=["move"], lease_seconds=120
    )
    assert handle.reconcile(observed(articulated_pose), stopped=True)
    try:
        yield service, handle
    finally:
        handle.release()


def proposal(service, turn, request_id):
    return {
        AUTHORITY: turn,
        "request_id": request_id,
        "expected_command_revision": service.get_world()["command_revision"],
        "action": {"kind": "move", "args": {"position": [0.2, 0.3]}},
    }


def error_text(result):
    return " ".join(block.text for block in result.content if block.type == "text")


def test_call_authority_is_explicit_and_exclusive_before_runtime_access(tmp_path):
    for value in (None, 0, 1, "true", [], {}):
        with pytest.raises(ValueError, match="explicitly"):
            create_server(None, call_authority=value)
    with pytest.raises(ValueError, match="mutually exclusive"):
        create_server(None, call_authority=True, turn_id="turn-" + "a" * 32)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "promethee.mcp_server",
            "--data-dir",
            str(tmp_path),
            "--turn-id",
            "turn-" + "a" * 32,
            "--call-authority",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 2
    assert "not allowed with argument" in result.stderr
    assert not (tmp_path / "world.sqlite3").exists()


def test_one_stdio_connection_keeps_each_turn_and_hidden_schema(body, tmp_path):
    service, handle = body
    first = service.begin_turn(timeout=120)

    async def run():
        fixed = await create_server(service, turn_id=first).list_tools()
        async with connect(tmp_path) as client:
            listed = (await client.list_tools()).tools
            assert {tool.name: tool.input_schema for tool in listed} == {
                tool.name: tool.input_schema for tool in fixed
            }
            assert len(listed) == 5
            for tool in listed:
                assert AUTHORITY not in json.dumps(tool.input_schema)
                assert "ctx" not in tool.input_schema.get("properties", {})
            request_a = proposal(service, first, "first-action")
            accepted_a = await client.call_tool("submit_action", request_a)
            assert accepted_a.structured_content["status"] == "accepted"
            assert accepted_a.structured_content["envelope"]["turn_id"] == first
            assert AUTHORITY not in accepted_a.structured_content["envelope"]
            assert request_a["action"] == {"kind": "move", "args": {"position": [0.2, 0.3]}}

            second = service.begin_turn(timeout=120)
            late = await client.call_tool("submit_action", proposal(service, first, "late-action"))
            assert late.is_error and "obsolete or expired" in error_text(late)
            cancel_a = await client.call_tool(
                "cancel_action", {AUTHORITY: first, "request_id": "first-action"}
            )
            assert cancel_a.is_error
            assert service.get("first-action")["status"] == "accepted"
            events = service.events()
            replay = await client.call_tool("submit_action", request_a)
            assert not replay.is_error and replay.structured_content["replayed"]
            assert service.events() == events
            changed = await client.call_tool("submit_action", {**request_a, AUTHORITY: second})
            assert changed.is_error and "different envelope" in error_text(changed)
            assert service.events() == events

            cancel_b = await client.call_tool(
                "cancel_action", {AUTHORITY: second, "request_id": "first-action"}
            )
            assert cancel_b.structured_content["status"] == "cancelled"
            accepted_b = await client.call_tool(
                "submit_action", proposal(service, second, "second-action")
            )
            assert accepted_b.structured_content["status"] == "accepted"
            assert accepted_b.structured_content["envelope"]["turn_id"] == second
            receipt = await client.call_tool(
                "read_execution", {AUTHORITY: second, "request_id": "first-action"}
            )
            assert receipt.structured_content["status"] == "cancelled"
            world = await client.call_tool("read_world", {AUTHORITY: second})
            assert world.structured_content["conversation"]["turn_id"] == second
            assert not (await client.call_tool("list_capabilities", {AUTHORITY: second})).is_error
            assert handle.claim_next()["request_id"] == "second-action"

    asyncio.run(run())


def test_missing_or_malformed_private_binding_cannot_use_current_turn(body, tmp_path):
    service, _handle = body
    turn = service.begin_turn(timeout=120)
    request = proposal(service, turn, "valid-action")
    bad_values = (None, True, 1, [], {}, "", turn.upper(), turn + "\n", turn + "0", "turn-a")

    async def run():
        async with connect(tmp_path) as client:
            assert (await client.call_tool("submit_action", request)).structured_content[
                "status"
            ] == "accepted"
            baseline, events = service.get_world(), service.events()
            calls = [
                ("read_world", {}),
                ("list_capabilities", {}),
                ("read_execution", {"request_id": "valid-action"}),
                ("cancel_action", {"request_id": "valid-action"}),
                ("submit_action", {**request, "request_id": "invalid-authority"}),
            ]
            for name, args in calls:
                args = {key: value for key, value in args.items() if key != AUTHORITY}
                for private in ({}, *({AUTHORITY: value} for value in bad_values)):
                    result = await client.call_tool(name, {**args, **private})
                    assert result.is_error, (name, private)
                    assert "per-call conversation turn" in error_text(result)
            assert service.get_world() == baseline
            assert service.events() == events

    asyncio.run(run())


def test_pending_stdio_call_keeps_old_authority_across_host_activation(body, tmp_path):
    service, _handle = body
    conversation = ConversationStore(service)
    first = conversation.begin("CPU test first turn", timeout=120)["turn_id"]
    request = proposal(service, first, "pending-old-action")
    entered = tmp_path / "submit-entered"

    async def run():
        async with connect(tmp_path, entered=entered) as client:
            with service.runtime.connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                pending = asyncio.create_task(client.call_tool("submit_action", request))
                deadline = monotonic() + 5
                while not entered.exists() and monotonic() < deadline:
                    await asyncio.sleep(0.01)
                assert entered.exists(), "The real MCP request did not reach submit."
                assert not pending.done()
                # Use the real host transaction implementation while the old
                # request is blocked before its admission transaction.
                second = conversation._begin(
                    conn, service.clock(), "CPU test second turn", timeout=120
                )["turn_id"]
                conn.commit()
            result = await asyncio.wait_for(pending, timeout=5)
            assert result.is_error and "obsolete or expired" in error_text(result)
            assert service.events() == []
            accepted = await client.call_tool(
                "submit_action", proposal(service, second, "fresh-after-pending")
            )
            assert accepted.structured_content["status"] == "accepted"
            assert accepted.structured_content["envelope"]["turn_id"] == second

    asyncio.run(run())


def test_expired_cancelled_and_unactivated_turns_remain_without_authority(body, tmp_path):
    service, _handle = body
    conversation = ConversationStore(service)
    clock = service.clock

    async def run():
        async with connect(tmp_path) as client:
            # Persist a deadline already expired for the subprocess's real clock;
            # no sleep or change to its clock is needed.
            service.clock = lambda: clock() - 5
            try:
                expired = conversation.begin("CPU expired", timeout=1)["turn_id"]
            finally:
                service.clock = clock
            refused = await client.call_tool(
                "submit_action", proposal(service, expired, "expired-call")
            )
            assert refused.is_error and "obsolete or expired" in error_text(refused)
            cancelled = conversation.begin("CPU cancelled", timeout=120)["turn_id"]
            conversation.abort(cancelled, status="interrupted")
            for turn, name in [(cancelled, "cancelled-call"), ("turn-" + uuid4().hex, "no-turn")]:
                result = await client.call_tool("submit_action", proposal(service, turn, name))
                assert result.is_error and "obsolete or expired" in error_text(result)
            assert service.events() == []

    asyncio.run(run())


def test_memory_authority_is_per_call_and_all_memory_tools_require_binding(tmp_path):
    pytest.importorskip("yaml")
    from promethee.memory import initialize_vault

    runtime = Runtime(tmp_path / "world.sqlite3", data_origin="session", session_kind="interactive")
    service = ExecutionService(runtime)
    conversation = ConversationStore(service)
    vault = initialize_vault(runtime, tmp_path / "vault")
    first = conversation.begin("CPU memory source", timeout=120)["turn_id"]
    note = {
        AUTHORITY: first,
        "note_id": "first-note",
        "kind": "summary",
        "title": "CPU fixture",
        "text": "Synthetic source for transport validation.",
        "sources": ["user:" + first],
    }

    async def run():
        async with connect(tmp_path, vault=vault) as client:
            listed = (await client.list_tools()).tools
            assert len(listed) == 9
            assert all(AUTHORITY not in json.dumps(tool.input_schema) for tool in listed)
            assert all("ctx" not in tool.input_schema.get("properties", {}) for tool in listed)
            created = await client.call_tool("write_memory_note", note)
            assert not created.is_error and not created.structured_content["replayed"]
            second = conversation.begin("CPU second source", timeout=120)["turn_id"]
            stale = await client.call_tool("write_memory_note", {**note, "note_id": "stale-note"})
            assert stale.is_error and "obsolete or expired" in error_text(stale)
            assert not (vault / "Promethee/Memory/stale-note.md").exists()
            replay = await client.call_tool("write_memory_note", note)
            assert not replay.is_error and replay.structured_content["replayed"]
            second_note = {**note, AUTHORITY: second, "note_id": "second-note"}
            assert not (await client.call_tool("write_memory_note", second_note)).is_error
            for name, args in [
                ("search_memory", {"query": "CPU"}),
                ("read_memory_note", {"note_id": "first-note"}),
                ("read_memory_source", {"source_id": "user:" + first}),
                (
                    "write_memory_note",
                    {key: value for key, value in note.items() if key != AUTHORITY},
                ),
            ]:
                assert not (await client.call_tool(name, {**args, AUTHORITY: second})).is_error
                for private in ({}, {AUTHORITY: False}, {AUTHORITY: "turn-invalid"}):
                    result = await client.call_tool(name, {**args, **private})
                    assert result.is_error and "per-call conversation turn" in error_text(result)
            with runtime.connection() as conn:
                assert conn.execute("SELECT count(*) FROM memory_notes").fetchone()[0] == 2

    asyncio.run(run())
