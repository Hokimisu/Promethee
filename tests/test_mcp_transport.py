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
async def connect(directory):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "promethee.mcp_server", "--data-dir", str(directory)],
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
        async with connect(tmp_path) as client:
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
        # A transport disconnect neither releases the body nor re-emits its request.
        assert handle.heartbeat()
        async with connect(tmp_path) as client:
            result = await client.call_tool("read_execution", {"request_id": "transport-one"})
            assert result.structured_content["status"] == "accepted"
            stopped = await client.call_tool("cancel_action", {"request_id": "transport-one"})
            assert stopped.structured_content["status"] == "cancelled"
            assert handle.claim_next() is None
            assert runtime.snapshot()["avatar"] == observation["avatar"]

    asyncio.run(run())
    handle.release()
