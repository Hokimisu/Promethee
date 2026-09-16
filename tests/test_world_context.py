"""CPU world pre-read contracts; stdio uses a synthetic pose, never a model."""

import asyncio
import copy
import json
from contextlib import contextmanager

import pytest
from conftest import Clock

from promethee.execution import ExecutionService
from promethee.mcp_server import WorldTools
from promethee.runtime import Runtime


def make_world(tmp_path, pose, *, clock=None, actions=("move", "posture"), lease=120):
    runtime = Runtime(
        tmp_path / "world.sqlite3", data_origin="session", session_kind="qualification"
    )
    service = ExecutionService(runtime, **({"clock": clock} if clock is not None else {}))
    driver = service.acquire_controller(
        source="kinematic", supported_actions=list(actions), lease_seconds=lease
    )
    state = runtime.snapshot()
    observation = {key: copy.deepcopy(state[key]) for key in ("avatar", "objects")}
    observation["pose"] = copy.deepcopy(pose)
    assert driver.reconcile(observation, stopped=True)
    return service, driver, observation


@pytest.fixture
def observed_world(tmp_path, articulated_pose):
    clock = Clock()
    service, driver, observation = make_world(tmp_path, articulated_pose, clock=clock, lease=5)
    try:
        yield service, driver, observation, clock
    finally:
        driver.release()


def dump_database(service):
    with service.runtime.connection() as conn:
        return list(conn.iterdump())


def test_default_and_false_flags_preserve_existing_snapshots(observed_world):
    service, _driver, observation, _clock = observed_world
    before = dump_database(service)
    ordinary = service.get_world()
    assert ordinary == service.get_world(include_supported_actions=False)
    assert "supported_actions" not in ordinary
    enriched = service.get_world(include_supported_actions=True)
    assert enriched.pop("supported_actions") == ["move", "posture"]
    assert enriched == ordinary

    tools = WorldTools(service)
    full = tools.world()
    assert full == tools.world(detail="full", include_capabilities=False)
    assert "capabilities" not in full and "supported_actions" not in full
    assert full["pose"] == observation["pose"]  # Python default remains full.
    summary = tools.world(detail="summary")
    assert summary == tools.world(detail="summary", include_capabilities=False)
    assert "pose" not in summary and "pose" in summary["projection"]["omitted"]
    enriched_full = tools.world(include_capabilities=True)
    capabilities = enriched_full.pop("capabilities")
    assert capabilities == tools.capabilities()
    assert enriched_full == full
    enriched_summary = tools.world(detail="summary", include_capabilities=True)
    assert enriched_summary.pop("capabilities") == capabilities
    assert enriched_summary == summary
    assert dump_database(service) == before


def test_enriched_response_is_not_persisted_or_an_alias_to_controller_state(observed_world):
    service, _driver, _observation, _clock = observed_world
    before = dump_database(service)
    snapshot = service.get_world(include_supported_actions=True)
    snapshot["supported_actions"].append("invented_action")
    snapshot["avatar"]["position"][0] = 999
    tools = WorldTools(service)
    enriched = tools.world(include_capabilities=True)
    enriched["capabilities"]["actions"][0]["required_args"].append("invented_argument")
    enriched["capabilities"]["actions"].append({"kind": "invented_action"})
    fresh = tools.world(include_capabilities=True)
    assert [action["kind"] for action in fresh["capabilities"]["actions"]] == ["move", "posture"]
    assert fresh["capabilities"]["actions"][0]["required_args"] == ["position"]
    assert fresh["avatar"]["position"] == [0, 0]
    assert dump_database(service) == before
    persisted = service.runtime.snapshot()
    assert "supported_actions" not in persisted and "capabilities" not in persisted


def test_supported_actions_are_read_on_the_world_connection_without_second_lookup(
    observed_world, monkeypatch
):
    service, _driver, _observation, _clock = observed_world
    actual_connection = service.runtime.connection
    connections = []

    @contextmanager
    def tracked_connection():
        with actual_connection() as conn:
            connections.append(conn)
            yield conn

    def separate_lookup():
        raise AssertionError("The world enrichment must not read a later controller snapshot")

    monkeypatch.setattr(service.runtime, "connection", tracked_connection)
    monkeypatch.setattr(service, "supported_actions", separate_lookup)
    snapshot = service.get_world(include_supported_actions=True, include_executions=True)
    assert len(connections) == 1
    assert snapshot["body"]["status"] == "confirmed"
    assert snapshot["supported_actions"] == ["move", "posture"]
    # The public world projection must use the enriched snapshot as well.
    projected = WorldTools(service).world(include_capabilities=True)
    assert projected["capabilities"]["actions"][0]["kind"] == "move"


def test_expired_controller_has_no_capabilities_in_its_interrupted_snapshot(observed_world):
    service, driver, observation, clock = observed_world
    original = service.get_world(include_supported_actions=True)
    service.submit(
        "expires-with-controller",
        action={"kind": "move", "args": {"position": [0.5, 0.2]}},
        expected_command_revision=original["command_revision"],
    )
    assert driver.claim_next()["request_id"] == "expires-with-controller"
    clock.advance(5)
    snapshot = WorldTools(service).world(include_capabilities=True)

    assert snapshot["capabilities"]["actions"] == []
    assert snapshot["body"]["status"] == "unconfirmed"
    assert snapshot["avatar"] == observation["avatar"]
    assert snapshot["pose"] == observation["pose"]
    assert snapshot["command_revision"] > original["command_revision"]
    receipt = snapshot["recent_executions"]["items"][0]
    assert receipt["request_id"] == "expires-with-controller"
    assert receipt["status"] == "interrupted"
    assert receipt["error"]["code"] == "controller_lost"
    assert not driver.heartbeat()
    assert WorldTools(service).world(include_capabilities=True) == snapshot
    assert service.get_world(include_supported_actions=True)["supported_actions"] == []


def test_replacement_controller_exposes_only_its_new_capabilities(observed_world):
    service, _driver, observation, clock = observed_world
    clock.advance(6)
    expired = WorldTools(service).world(include_capabilities=True)
    assert expired["capabilities"]["actions"] == []
    replacement = service.acquire_controller(
        source="kinematic", supported_actions=["posture"], lease_seconds=30
    )
    try:
        assert replacement.reconcile(observation, stopped=True)
        current = WorldTools(service).world(include_capabilities=True)
        assert current["body"]["status"] == "confirmed"
        assert current["command_revision"] > expired["command_revision"]
        assert [item["kind"] for item in current["capabilities"]["actions"]] == ["posture"]
        assert current["capabilities"]["actions"][0]["names"] == ["arms_raised", "standing"]
    finally:
        replacement.release()


def test_world_without_a_controller_does_not_advertise_the_logical_catalogue(tmp_path):
    service = ExecutionService(
        Runtime(tmp_path / "world.sqlite3", data_origin="session", session_kind="qualification")
    )
    snapshot = WorldTools(service).world(include_capabilities=True)
    assert snapshot["capabilities"]["actions"] == []
    assert "supported_actions" not in snapshot
    assert service.events() == []
    assert "capabilities" not in service.runtime.snapshot()


def test_stdio_world_capabilities_schema_values_and_associated_revision_guard(
    tmp_path, articulated_pose
):
    pytest.importorskip("mcp")
    from test_mcp_transport import connect

    service, driver, observation = make_world(
        tmp_path, articulated_pose, actions=("move", "posture", "spawn", "take", "place")
    )
    turn = service.begin_turn(timeout=120)

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
            schema = listed["read_world"].input_schema
            option = schema["properties"]["include_capabilities"]
            assert option["type"] == "boolean" and option["default"] is False
            assert "include_capabilities" not in schema.get("required", [])

            default = await client.call_tool("read_world")
            explicit_false = await client.call_tool("read_world", {"include_capabilities": False})
            assert (
                not default.is_error
                and default.structured_content == explicit_false.structured_content
            )
            assert "capabilities" not in default.structured_content
            assert "pose" not in default.structured_content
            response = await client.call_tool("read_world", {"include_capabilities": True})
            assert not response.is_error
            snapshot = response.structured_content
            capabilities = snapshot["capabilities"]
            separate = await client.call_tool("list_capabilities")
            assert capabilities == separate.structured_content
            assert "supported_actions" not in snapshot
            actions = {item["kind"]: item for item in capabilities["actions"]}
            assert set(actions) == {"move", "posture", "spawn", "take", "place"}
            assert actions["move"]["required_args"] == ["position"]
            assert actions["posture"]["required_args"] == ["name"]
            assert actions["posture"]["names"] == ["arms_raised", "standing"]
            assert actions["spawn"]["required_args"] == ["asset", "object_id", "position"]
            assert actions["spawn"]["spatial_models"] == ["ball", "plush"]
            assert actions["take"]["required_args"] == ["object_id"]
            assert actions["take"]["spatial_models"] == ["ball", "plush"]
            assert "no finger closure or physics" in actions["take"]["contact"]
            assert actions["place"]["required_args"] == ["position"]
            assert "[x, y, z]" in actions["place"]["position_format"]
            assert "no gravity" in actions["place"]["free_objects"]
            assert snapshot["conversation"]["turn_id"] == turn

            # A presence-only pose change may follow the read, with no rebasing by the caller.
            changed = copy.deepcopy(observation)
            changed["pose"]["positions"][7][0] += 0.01
            assert driver.observe_idle(changed)
            current = service.get_world()
            assert current["revision"] > snapshot["revision"]
            assert current["command_revision"] == snapshot["command_revision"]
            accepted = await client.call_tool(
                "submit_action",
                {
                    "request_id": "from-enriched-world",
                    "expected_command_revision": snapshot["command_revision"],
                    "action": {"kind": "move", "args": {"position": [0.2, 0.3]}},
                },
            )
            assert not accepted.is_error and accepted.structured_content["status"] == "accepted"
            assert accepted.structured_content["envelope"]["turn_id"] == turn
            assert service.get_world()["avatar"] == observation["avatar"]
            assert driver.claim_next()["request_id"] == "from-enriched-world"

    try:
        asyncio.run(run())
    finally:
        driver.release()


def test_stdio_include_capabilities_rejects_nonbooleans_without_effect(tmp_path, articulated_pose):
    pytest.importorskip("mcp")
    from test_mcp_transport import connect

    service, driver, _observation = make_world(tmp_path, articulated_pose)
    turn = service.begin_turn(timeout=120)

    async def run():
        async with connect(tmp_path, turn) as client:
            before = dump_database(service)
            for value in (None, 0, 1, "true", "false", [], {}):
                response = await client.call_tool("read_world", {"include_capabilities": value})
                assert response.is_error, json.dumps(value)
            assert dump_database(service) == before
            default = await client.call_tool("read_world")
            assert "capabilities" not in default.structured_content

    try:
        asyncio.run(run())
    finally:
        driver.release()
