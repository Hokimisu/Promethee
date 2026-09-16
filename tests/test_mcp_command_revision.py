"""Real MCP stdio checks with synthetic CPU poses, never a model or motor trial."""

import asyncio
import copy

import pytest

pytest.importorskip("mcp")

from test_appearance_checkpoint import observed  # noqa: E402
from test_mcp_transport import connect  # noqa: E402

from promethee.execution import ExecutionService  # noqa: E402
from promethee.runtime import Runtime  # noqa: E402


@pytest.fixture
def command_body(tmp_path, articulated_pose):
    runtime = Runtime(
        tmp_path / "world.sqlite3", data_origin="session", session_kind="qualification"
    )
    service = ExecutionService(runtime)
    handle = service.acquire_controller(
        source="kinematic", supported_actions=["move"], lease_seconds=60
    )
    assert handle.reconcile(observed(articulated_pose), stopped=True)
    try:
        yield service, handle
    finally:
        handle.release()


def test_stdio_schema_and_strict_exclusive_revision_guards(command_body, tmp_path):
    service, _handle = command_body

    async def run():
        turn = service.begin_turn()
        async with connect(tmp_path, turn) as client:
            listed = await client.list_tools()
            assert {tool.name for tool in listed.tools} == {
                "read_world",
                "list_capabilities",
                "submit_action",
                "read_execution",
                "cancel_action",
            }
            submit = next(tool for tool in listed.tools if tool.name == "submit_action")
            schema = submit.input_schema
            assert set(schema["required"]) == {"request_id", "action"}
            assert set(schema["properties"]) == {
                "request_id",
                "action",
                "expected_revision",
                "expected_command_revision",
            }
            for guard in ("expected_revision", "expected_command_revision"):
                field = schema["properties"][guard]
                assert {option["type"] for option in field["anyOf"]} == {"integer", "null"}
                assert field["default"] is None

            snapshot = await client.call_tool("read_world")
            assert not snapshot.is_error
            world = snapshot.structured_content
            for key in ("revision", "command_revision"):
                assert type(world[key]) is int and world[key] >= 0
            valid = {
                "expected_revision": world["revision"],
                "expected_command_revision": world["command_revision"],
            }
            invalid = [
                {},
                {"expected_revision": None},
                {"expected_command_revision": None},
                {"expected_revision": None, "expected_command_revision": None},
                valid,
            ]
            for guard in valid:
                invalid.extend({guard: value} for value in (True, False, "1", "0", 1.0, -1))
            before = service.get_world()
            for index, guards in enumerate(invalid):
                result = await client.call_tool(
                    "submit_action",
                    {
                        "request_id": f"invalid-guard-{index}",
                        "action": {"kind": "move", "args": {"position": [0.2, 0.3]}},
                        **guards,
                    },
                )
                assert result.is_error, guards
                assert service.get_world() == before, guards
                assert service.events() == [], guards

    asyncio.run(run())


@pytest.mark.parametrize("guard", ["expected_revision", "expected_command_revision"])
def test_stdio_idle_pose_only_preserves_command_guard(
    command_body, tmp_path, articulated_pose, guard
):
    service, handle = command_body

    async def run():
        turn = service.begin_turn()
        async with connect(tmp_path, turn) as client:
            original = (await client.call_tool("read_world")).structured_content
            pose = copy.deepcopy(articulated_pose)
            pose["positions"][7][0] += 0.01
            assert handle.observe_idle(observed(pose))
            current = (await client.call_tool("read_world")).structured_content
            assert current["revision"] == original["revision"] + 1
            assert current["command_revision"] == original["command_revision"]
            assert current["pose"] == pose
            assert service.events() == []
            other = (
                "expected_command_revision" if guard == "expected_revision" else "expected_revision"
            )
            request = {
                "request_id": "after-idle",
                "action": {"kind": "move", "args": {"position": [0.2, 0.3]}},
                guard: original[guard.removeprefix("expected_")],
                other: None,
            }
            result = await client.call_tool("submit_action", request)
            assert not result.is_error
            receipt = result.structured_content
            if guard == "expected_revision":
                assert receipt["status"] == "rejected"
                assert receipt["error"]["code"] == "revision_conflict"
                assert handle.claim_next() is None
            else:
                assert receipt["status"] == "accepted"
                assert not receipt["replayed"]
                assert receipt["envelope"][guard] == original["command_revision"]
                events = service.events()
                replay = await client.call_tool("submit_action", request)
                assert not replay.is_error and replay.structured_content["replayed"]
                assert service.events() == events
                assert handle.claim_next()["request_id"] == "after-idle"
            # A request or rejection cannot invent the requested displacement.
            assert service.get_world()["avatar"] == current["avatar"]
            assert service.get_world()["pose"] == pose

    asyncio.run(run())


def test_stdio_command_guard_does_not_reauthorize_an_obsolete_turn(command_body, tmp_path):
    service, _handle = command_body

    async def run():
        old_turn = service.begin_turn()
        async with connect(tmp_path, old_turn) as client:
            service.begin_turn()
            fresh = (await client.call_tool("read_world")).structured_content
            before = service.get_world()
            result = await client.call_tool(
                "submit_action",
                {
                    "request_id": "obsolete-command-guard",
                    "expected_command_revision": fresh["command_revision"],
                    "action": {"kind": "move", "args": {"position": [0.2, 0.3]}},
                },
            )
            assert result.is_error
            assert service.get_world() == before
            assert service.events() == []

    asyncio.run(run())
