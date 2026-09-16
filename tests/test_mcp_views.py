"""Real stdio/schema checks with synthetic CPU observations; no agent inference."""

import asyncio
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from test_appearance_checkpoint import observed  # noqa: E402
from test_mcp_transport import connect  # noqa: E402

from promethee.execution import ExecutionService  # noqa: E402
from promethee.mcp_server import WorldTools  # noqa: E402
from promethee.runtime import Runtime  # noqa: E402
from promethee.world import BODY_ACTION_FIELDS  # noqa: E402


@pytest.fixture
def observed_tools(tmp_path, articulated_pose):
    runtime = Runtime(
        tmp_path / "world.sqlite3", data_origin="session", session_kind="qualification"
    )
    service = ExecutionService(runtime)
    handle = service.acquire_controller(
        source="kinematic", supported_actions=list(BODY_ACTION_FIELDS), lease_seconds=120
    )
    observation = observed(articulated_pose)
    assert handle.reconcile(observation, stopped=True)
    try:
        yield service, handle, observation
    finally:
        handle.release()


def assert_projection(full, summary, omitted):
    """Independent oracle: delete exactly the declared paths and nothing else."""
    expected = copy.deepcopy(full)
    for path in omitted:
        parts = path.split(".")
        parent = expected
        for part in parts[:-1]:
            parent = parent[part]
        del parent[parts[-1]]
    expected["projection"] = {"detail": "summary", "omitted": omitted}
    assert summary == expected


def assert_action_schema(schema):
    action = schema["properties"]["action"]
    assert action["type"] == "object"
    assert set(action["required"]) == {"kind", "args"}
    assert action["additionalProperties"] is False
    assert set(action["properties"]) == {"kind", "args"}
    assert action["properties"]["kind"]["type"] == "string"
    assert set(action["properties"]["kind"]["enum"]) == set(BODY_ACTION_FIELDS)
    # A nested object type would make native Hermes silently decode JSON strings.
    args = action["properties"]["args"]
    assert "type" not in args
    assert "JSON object, never a JSON-encoded string" in args["description"]
    examples = action["examples"]
    assert any(
        example == {"kind": "posture", "args": {"name": "arms_raised"}} for example in examples
    )
    for example in examples:
        assert set(example) == {"kind", "args"}
        assert set(example["args"]) == BODY_ACTION_FIELDS[example["kind"]]


def test_stdio_summary_defaults_and_explicit_full_are_exact(observed_tools, tmp_path):
    service, handle, observation = observed_tools
    turn = service.begin_turn(timeout=120)
    service.submit(
        "observed-receipt",
        action={"kind": "posture", "args": {"name": "standing"}},
        expected_command_revision=service.get_world()["command_revision"],
        turn_id=turn,
    )
    assert handle.claim_next()["request_id"] == "observed-receipt"
    assert handle.feedback("observed-receipt", 0, "running", observation=observation)
    assert handle.feedback("observed-receipt", 1, "completed", observation=observation)
    world = service.get_world(include_executions=True)
    receipt = service.get("observed-receipt")
    # The Python API retains its full default despite the MCP default changing.
    direct = WorldTools(service, turn_id=turn)
    assert direct.world() == world
    assert direct.execution("observed-receipt") == receipt

    async def run():
        async with connect(tmp_path, turn) as client:
            listed = {tool.name: tool for tool in (await client.list_tools()).tools}
            assert set(listed) == {
                "read_world",
                "list_capabilities",
                "submit_action",
                "read_execution",
                "cancel_action",
            }
            for name in ("read_world", "read_execution"):
                schema = listed[name].input_schema
                detail = schema["properties"]["detail"]
                assert detail["type"] == "string"
                assert set(detail["enum"]) == {"summary", "full"}
                assert detail["default"] == "summary"
                assert "detail" not in schema.get("required", [])
            assert_action_schema(listed["submit_action"].input_schema)
            for tool, args, full, omitted in [
                ("read_world", {}, world, ["pose", "appearance"]),
                (
                    "read_execution",
                    {"request_id": "observed-receipt"},
                    receipt,
                    ["observation.pose", "observation.appearance"],
                ),
            ]:
                default = await client.call_tool(tool, args)
                summary = await client.call_tool(tool, {**args, "detail": "summary"})
                complete = await client.call_tool(tool, {**args, "detail": "full"})
                assert not default.is_error and not summary.is_error and not complete.is_error
                assert complete.structured_content == full
                assert default.structured_content == summary.structured_content
                assert_projection(full, summary.structured_content, omitted)
                # Hermes consumes textual content first. The same projection must
                # be there, not only in MCP structuredContent.
                texts = [block.text for block in summary.content if block.type == "text"]
                assert len(texts) == 1
                assert json.loads(texts[0]) == summary.structured_content
            assert service.get_world(include_executions=True) == world
            assert service.get("observed-receipt") == receipt

    asyncio.run(run())


def test_stdio_summary_preserves_unconfirmed_body_and_rejection_without_observation(tmp_path):
    service = ExecutionService(Runtime(tmp_path / "world.sqlite3", data_origin="session"))
    turn = service.begin_turn(timeout=120)
    service.submit(
        "no-controller",
        action={"kind": "move", "args": {"position": [0.2, 0.3]}},
        expected_command_revision=service.get_world()["command_revision"],
        turn_id=turn,
    )
    world = service.get_world(include_executions=True)
    receipt = service.get("no-controller")
    assert world["body"]["status"] == "unconfirmed"
    assert world["pose"] is None and world["appearance"] is None
    assert "observation" not in receipt

    async def run():
        async with connect(tmp_path, turn) as client:
            result = await client.call_tool("read_world")
            assert not result.is_error
            assert_projection(world, result.structured_content, ["pose", "appearance"])
            result = await client.call_tool("read_execution", {"request_id": "no-controller"})
            assert not result.is_error
            assert_projection(receipt, result.structured_content, [])
            assert result.structured_content["error"]["code"] == "controller_unavailable"
            assert "observation" not in result.structured_content

    asyncio.run(run())


def test_stdio_invalid_detail_is_rejected_without_mutation(observed_tools, tmp_path):
    service, _handle, _observation = observed_tools
    turn = service.begin_turn(timeout=120)
    service.submit(
        "bad-action",
        action={"kind": "unsupported", "args": {}},
        expected_command_revision=service.get_world()["command_revision"],
        turn_id=turn,
    )
    world, receipt, events = service.get_world(), service.get("bad-action"), service.events()

    async def run():
        async with connect(tmp_path, turn) as client:
            for detail in (None, True, 1, "Summary", "full ", "brief", [], {}):
                for tool, args in [
                    ("read_world", {}),
                    ("read_execution", {"request_id": "bad-action"}),
                ]:
                    result = await client.call_tool(tool, {**args, "detail": detail})
                    assert result.is_error, (tool, detail)
            assert service.get_world() == world
            assert service.get("bad-action") == receipt
            assert service.events() == events

    asyncio.run(run())


def test_stdio_schema_does_not_repair_actions_or_bypass_durable_refusals(observed_tools, tmp_path):
    service, handle, observation = observed_tools
    turn = service.begin_turn(timeout=120)
    bad_actions = [
        {"kind": "posture", "name": "arms_raised"},
        {"kind": "posture", "args": {"name": "arms_raised"}, "extra": True},
        {"kind": "posture", "args": {"name": True}},
        {"kind": "posture", "args": {"name": 1}},
        {"kind": "posture", "args": {"name": " arms_raised "}},
        {"kind": "posture", "args": '{"name":"arms_raised"}'},
        {"kind": "move", "args": {"position": ["0.2", 0.3]}},
        {"kind": "move", "args": {"position": [True, 0.3]}},
        {"kind": "move", "args": [["position", [0.2, 0.3]]]},
        {"kind": "fly", "args": {}},
        {"kind": "stand", "args": {"ignored": 1}},
        {"args": {}},
        {},
    ]

    async def run():
        async with connect(tmp_path, turn) as client:
            for index, action in enumerate(bad_actions):
                request = {
                    "request_id": f"unrepaired-{index}",
                    "expected_command_revision": service.get_world()["command_revision"],
                    "action": action,
                }
                result = await client.call_tool("submit_action", request)
                # A misleading action shape is still a durable runtime rejection,
                # not a new Pydantic transport error that loses the request ledger.
                assert not result.is_error, action
                assert result.structured_content["status"] == "rejected"
                assert result.structured_content["error"]["code"] == "invalid_action"
                stored = service.get(request["request_id"])
                assert json.dumps(stored["envelope"]["action"], sort_keys=True) == json.dumps(
                    action, sort_keys=True
                )
                events = service.events()
                replay = await client.call_tool("submit_action", request)
                assert not replay.is_error and replay.structured_content["replayed"]
                assert service.events() == events
                changed = await client.call_tool(
                    "submit_action",
                    {
                        **request,
                        "action": {"kind": "posture", "args": {"name": "arms_raised"}},
                    },
                )
                assert changed.is_error
                assert service.events() == events
                assert service.get(request["request_id"]) == stored
                assert handle.claim_next() is None
            current = service.get_world()
            assert current["avatar"] == observation["avatar"]
            assert current["pose"] == observation["pose"]
            assert current["appearance"] == observation["appearance"]
            accepted = await client.call_tool(
                "submit_action",
                {
                    "request_id": "valid-nested-args",
                    "expected_command_revision": current["command_revision"],
                    "action": {"kind": "posture", "args": {"name": "arms_raised"}},
                },
            )
            assert not accepted.is_error
            assert accepted.structured_content["status"] == "accepted"
            assert handle.claim_next()["request_id"] == "valid-nested-args"

    asyncio.run(run())


def test_stdio_schema_survives_optional_native_hermes_conversion(observed_tools, tmp_path):
    """Use upstream conversion/coercion with a mocked registry; no agent startup."""
    checkout = Path(
        os.environ.get(
            "PROMETHEE_TEST_HERMES_ROOT",
            Path(__file__).resolve().parents[1] / ".local/hermes-agent",
        )
    )
    if not (checkout / "tools/mcp_tool_schema.py").is_file():
        pytest.skip("Optional native Hermes checkout is not installed.")
    service, _handle, _observation = observed_tools
    turn = service.begin_turn(timeout=120)

    async def collect():
        async with connect(tmp_path, turn) as client:
            return [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
                for tool in (await client.list_tools()).tools
            ]

    original = asyncio.run(collect())
    request = {
        "request_id": "native-unrepaired-json-args",
        "expected_command_revision": service.get_world()["command_revision"],
        "action": {"kind": "posture", "args": '{"name":"arms_raised"}'},
    }
    conversion = """import copy,json,sys
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
from tools.mcp_tool_schema import _convert_mcp_schema
from tools.arg_coercion import coerce_tool_args,registry
payload=json.load(sys.stdin)
converted=[_convert_mcp_schema('promethee',SimpleNamespace(**tool))
           for tool in payload['tools']]
name='mcp__promethee__submit_action'
schema=next(tool for tool in converted if tool['name']==name)
with patch.object(registry,'get_schema',return_value=schema) as lookup:
    request=coerce_tool_args(name,copy.deepcopy(payload['request']))
    lookup.assert_called_once_with(name)
# Positive control: prove this is the real native repair path that caused the bug.
old_schema=copy.deepcopy(schema)
old_schema['parameters']['properties']['action']['properties']['args']['type']='object'
with patch.object(registry,'get_schema',return_value=old_schema):
    old_request=coerce_tool_args(name,copy.deepcopy(payload['request']))
print(json.dumps({'tools':converted,'request':request,'old_request':old_request}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", conversion, str(checkout.resolve())],
        input=json.dumps({"tools": original, "request": request}),
        text=True,
        capture_output=True,
        check=True,
        timeout=20,
    )
    native = json.loads(completed.stdout)
    converted = {tool["name"]: tool for tool in native["tools"]}
    assert set(converted) == {"mcp__promethee__" + tool["name"] for tool in original}
    assert_action_schema(converted["mcp__promethee__submit_action"]["parameters"])
    for name in ("read_world", "read_execution"):
        detail = converted["mcp__promethee__" + name]["parameters"]["properties"]["detail"]
        assert set(detail["enum"]) == {"summary", "full"}
        assert detail["default"] == "summary"
    assert native["old_request"]["action"]["args"] == {"name": "arms_raised"}
    assert native["request"] == request
    assert isinstance(native["request"]["action"]["args"], str)

    async def submit_native_result():
        async with connect(tmp_path, turn) as client:
            result = await client.call_tool("submit_action", native["request"])
            assert not result.is_error
            assert result.structured_content["status"] == "rejected"
            assert result.structured_content["error"]["code"] == "invalid_action"
            stored = service.get(request["request_id"])
            assert stored["envelope"]["action"] == request["action"]
            events = service.events()
            replay = await client.call_tool("submit_action", native["request"])
            assert not replay.is_error and replay.structured_content["replayed"]
            assert service.events() == events
            assert service.get(request["request_id"]) == stored

    asyncio.run(submit_native_result())
