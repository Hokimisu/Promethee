"""Optional real stdio transport checks; the body is an explicit CPU test driver."""

import asyncio
import copy
import sys
from contextlib import asynccontextmanager

import pytest

pytest.importorskip("mcp")

from mcp.client.session import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

from promethee.execution import ExecutionService  # noqa: E402
from promethee.runtime import Runtime  # noqa: E402


@asynccontextmanager
async def connect(directory, turn_id, vault=None):
    args = ["-m", "promethee.mcp_server", "--data-dir", str(directory), "--turn-id", turn_id]
    if vault is not None:
        args += ["--vault", str(vault)]
    params = StdioServerParameters(
        command=sys.executable,
        args=args,
    )
    async with stdio_client(params) as streams, ClientSession(*streams) as client:
        await client.initialize()
        yield client


def test_stdio_tools_idempotence_validation_and_restart(tmp_path, articulated_pose):
    runtime = Runtime(tmp_path / "world.sqlite3", data_origin="session")
    service = ExecutionService(runtime)
    handle = service.acquire_controller(
        source="kinematic", supported_actions=["move"], lease_seconds=60
    )
    state = runtime.snapshot()
    observation = {key: copy.deepcopy(state[key]) for key in ("avatar", "objects")}
    observation["pose"] = articulated_pose
    handle.reconcile(observation, stopped=True)

    async def run():
        turn = service.begin_turn()
        async with connect(tmp_path, turn) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "read_world",
                "list_capabilities",
                "submit_action",
                "read_execution",
                "cancel_action",
            }
            world = await client.call_tool("read_world")
            assert not world.is_error
            assert world.structured_content["world_id"] == state["world_id"]
            revision = world.structured_content["revision"]
            args = {
                "request_id": "transport-one",
                "expected_revision": revision,
                "action": {"kind": "move", "args": {"position": [0.2, 0.3]}},
            }
            malformed = await client.call_tool("submit_action", {**args, "expected_revision": True})
            assert malformed.is_error
            assert service.events() == []
            submitted = await client.call_tool("submit_action", args)
            assert submitted.structured_content["status"] == "accepted"
            replayed = await client.call_tool("submit_action", args)
            assert replayed.structured_content["replayed"]
            forbidden = await client.call_tool("feedback", {"status": "completed"})
            assert forbidden.is_error
            next_turn = service.begin_turn()
            fresh = await client.call_tool("read_world")
            late = await client.call_tool(
                "submit_action",
                {
                    **args,
                    "request_id": "late-proposal",
                    "expected_revision": fresh.structured_content["revision"],
                },
            )
            assert late.is_error
            late_cancel = await client.call_tool("cancel_action", {"request_id": "transport-one"})
            assert late_cancel.is_error
            assert service.get("transport-one")["status"] == "accepted"
        # A transport disconnect neither releases the body nor re-emits its request.
        assert handle.heartbeat()
        async with connect(tmp_path, next_turn) as client:
            result = await client.call_tool("read_execution", {"request_id": "transport-one"})
            assert result.structured_content["status"] == "accepted"
            stopped = await client.call_tool("cancel_action", {"request_id": "transport-one"})
            assert stopped.structured_content["status"] == "cancelled"
            assert handle.claim_next() is None
            assert runtime.snapshot()["avatar"] == observation["avatar"]

    asyncio.run(run())
    handle.release()


def test_sourced_memory_and_correction_over_stdio(tmp_path):
    pytest.importorskip("yaml")
    from promethee.conversation import ConversationStore
    from promethee.memory import initialize_vault

    runtime = Runtime(tmp_path / "world.sqlite3", data_origin="session", session_kind="interactive")
    service = ExecutionService(runtime)
    conversation = ConversationStore(service)
    vault = initialize_vault(runtime, tmp_path / "vault")

    async def run():
        turn = conversation.begin("Developer fixture: blue object.")["turn_id"]
        async with connect(tmp_path, turn, vault) as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 9
            source = await client.call_tool("read_memory_source", {"source_id": "user:" + turn})
            assert source.structured_content["content"] == "Developer fixture: blue object."
            args = {
                "note_id": "blue",
                "kind": "summary",
                "title": "Blue object",
                "text": "A blue object was mentioned.",
                "sources": ["user:" + turn],
            }
            invalid = await client.call_tool("write_memory_note", {**args, "sources": []})
            assert invalid.is_error
            result = await client.call_tool("write_memory_note", args)
            assert not result.is_error and not result.structured_content["replayed"]
            replay = await client.call_tool("write_memory_note", args)
            assert replay.structured_content["replayed"]
            next_turn = conversation.begin("Developer correction: red object.")["turn_id"]
            late = await client.call_tool("write_memory_note", {**args, "note_id": "late"})
            assert late.is_error
        async with connect(tmp_path, next_turn, vault) as client:
            correction = await client.call_tool(
                "write_memory_note",
                {
                    "note_id": "red",
                    "kind": "correction",
                    "title": "Correction",
                    "text": "The mentioned object was red.",
                    "sources": ["user:" + next_turn],
                    "corrects": "blue",
                },
            )
            assert not correction.is_error
            result = await client.call_tool("search_memory", {"query": "blue"})
            assert [n["note_id"] for n in result.structured_content["notes"]] == ["red"]
            read = await client.call_tool("read_memory_note", {"note_id": "blue"})
            assert read.structured_content["note_id"] == "red"
            assert service.events() == []

    asyncio.run(run())
