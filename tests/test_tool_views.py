"""Projection fidelity on real Runtime snapshots with explicit synthetic observations."""

import copy
import json

import pytest
from conftest import Clock
from test_appearance_checkpoint import observed

from promethee.conversation import ConversationStore
from promethee.execution import ExecutionService
from promethee.initiative import Initiative
from promethee.runtime import Runtime
from promethee.spatial import attachment_transform
from promethee.tool_views import project_execution, project_world


@pytest.fixture
def world(tmp_path, articulated_pose):
    clock = Clock()
    service = ExecutionService(
        Runtime(tmp_path / "world.sqlite3", data_origin="session", session_kind="qualification"),
        clock=clock,
    )
    driver = service.acquire_controller(source="kinematic", supported_actions=["move"])
    observation = observed(articulated_pose)
    attachment = {
        "joint": "RightHand",
        "position": [0.0, 0.0, 0.0],
        "rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    }
    observation["avatar"]["holding"] = "held"
    observation["appearance"]["aligned_hands"] = ["RightHand"]
    observation["objects"] = {
        "held": {
            "asset": "plush",
            "position": [0.0, 0.0],
            "spatial": {
                **attachment_transform(attachment, observation["pose"]),
                "attachment": attachment,
            },
        },
        "seat": {"asset": "chair", "position": [2.0, 0.0]},
    }
    assert driver.reconcile(observation, stopped=True)
    initiative = Initiative(service)
    initiative.configure(budget=3, interval=10)
    initiative.update(paused=True)
    store = ConversationStore(service)
    opened = store.begin("Qualification de projection.")
    store.finish(
        opened["turn_id"],
        {
            "type": "result",
            "turn_id": opened["turn_id"],
            "failed": False,
            "interrupted": False,
            "text": "Réponse synthétique de test.",
            "messages": [
                {"role": "user", "content": "Qualification de projection."},
                {"role": "assistant", "content": "Réponse synthétique de test."},
            ],
        },
    )
    store.speech_delivery(opened["turn_id"], "test-speech", "preparing")
    store.speech_delivery(opened["turn_id"], "test-speech", "playing")
    store.speech_delivery(opened["turn_id"], "test-speech", "interrupted")
    store.begin("Second tour synthétique.")
    yield service, driver, observation, clock
    driver.release()


def without(data, *fields):
    return {key: value for key, value in data.items() if key not in fields}


@pytest.mark.parametrize("confirmed", [True, False])
def test_world_projection_preserves_every_other_field_and_full_snapshot(world, confirmed):
    service, driver, _, _ = world
    if not confirmed:
        driver.release()
    source = service.get_world(include_executions=True)
    before = copy.deepcopy(source)
    assert source["body"]["status"] == ("confirmed" if confirmed else "unconfirmed")
    assert source["pose"] is not None and source["appearance"] is not None
    assert source["objects"]["held"]["spatial"]["attachment"]["joint"] == "RightHand"
    assert source["conversation"] is not None
    assert source["initiative"]["paused"] is True
    assert source["recent_speech_deliveries"]["items"][0]["delivery"]["status"] == "interrupted"
    projected = project_world(source)
    assert projected["projection"] == {"detail": "summary", "omitted": ["pose", "appearance"]}
    assert without(projected, "projection") == without(source, "pose", "appearance")
    assert project_world(source, detail="full") == before
    assert "projection" not in project_world(source, detail="full")
    assert source == before
    assert service.get_world(include_executions=True) == before


def test_initial_unconfirmed_world_is_not_presented_as_observed(tmp_path):
    service = ExecutionService(
        Runtime(tmp_path / "world.sqlite3", data_origin="session", session_kind="qualification")
    )
    source = service.get_world()
    assert source["pose"] is None and source["appearance"] is None
    projected = project_world(source)
    assert projected["body"] == {"status": "unconfirmed", "observed_at": None, "source": None}
    assert projected["projection"]["omitted"] == ["pose", "appearance"]
    assert "pose" not in projected and "appearance" not in projected
    assert without(projected, "projection") == without(source, "pose", "appearance")


@pytest.mark.parametrize(
    "status", ["rejected", "accepted", "running", "completed", "cancelled", "interrupted", "failed"]
)
def test_execution_projection_preserves_receipt_authority_at_each_lifecycle_state(world, status):
    service, driver, observation, clock = world
    snapshot = service.get_world()
    revision = snapshot["command_revision"] - (1 if status == "rejected" else 0)
    action = {"kind": "move", "args": {"position": [0, 0]}}
    service.submit("projection-test", action=action, expected_command_revision=revision)
    if status not in {"rejected", "accepted"}:
        assert driver.claim_next()["request_id"] == "projection-test"
        assert driver.feedback("projection-test", 0, "running", observation=observation)
        if status == "interrupted":
            clock.advance(6)
        elif status in {"completed", "cancelled", "failed"}:
            if status == "cancelled":
                service.cancel("projection-test")
                driver.claim_cancellation()
            assert driver.feedback(
                "projection-test",
                1,
                status,
                observation=observation,
                error="Synthetic driver failure." if status == "failed" else None,
            )
    source = service.get("projection-test")
    assert source["status"] == status
    before = copy.deepcopy(source)
    projected = project_execution(source)
    assert without(projected, "projection", "observation") == without(source, "observation")
    if "observation" in source:
        assert projected["observation"] == without(source["observation"], "pose", "appearance")
        assert projected["projection"]["omitted"] == ["observation.pose", "observation.appearance"]
    else:
        assert "observation" not in projected
        assert projected["projection"]["omitted"] == []
    assert project_execution(source, detail="full") == before
    assert "projection" not in project_execution(source, detail="full")
    assert source == before and service.get("projection-test") == before


@pytest.mark.parametrize("detail", ["summary", "full"])
def test_outputs_never_share_mutable_aliases_with_input_or_other_calls(world, detail):
    service, _, _, _ = world
    snapshot = service.get_world(include_executions=True)
    receipt = {"observation": snapshot, "envelope": {"action": {"args": {"name": "standing"}}}}
    before = copy.deepcopy((snapshot, receipt))
    world_view = project_world(snapshot, detail=detail)
    execution_view = project_execution(receipt, detail=detail)
    other = project_execution(receipt, detail=detail)
    world_view["objects"]["held"]["spatial"]["attachment"]["position"][0] = 5
    world_view["initiative"]["paused"] = False
    execution_view["observation"]["avatar"]["position"][0] = 4
    execution_view["envelope"]["action"]["args"]["name"] = "changed"
    if detail == "full":
        world_view["pose"]["positions"][0][0] = 3
        execution_view["observation"]["appearance"]["frame"]["root_y_offset"] = 0
    assert (snapshot, receipt) == before
    assert other == project_execution(receipt, detail=detail)


@pytest.mark.parametrize("observation", [None, {}, {"pose": None}, {"appearance": None}])
def test_execution_omits_only_fields_present_and_preserves_null_or_empty_observation(observation):
    source = {"status": "interrupted", "observation": observation, "error": {"code": "lost"}}
    result = project_execution(source)
    if observation is None:
        assert result["observation"] is None
        expected = []
    else:
        assert result["observation"] == {}
        expected = [
            "observation." + field for field in ("pose", "appearance") if field in observation
        ]
    assert result["projection"]["omitted"] == expected
    assert result["error"] == source["error"]


def test_projection_paths_do_not_remove_similarly_named_metadata_or_nested_data():
    source = {
        "activity": {"pose": "requested, not observed", "appearance": "user data"},
        "objects": {"sign": {"text": "pose", "metadata": {"appearance": "opaque"}}},
        "new_field": {"retained": [1, 2]},
    }
    assert project_world(source) == {**source, "projection": {"detail": "summary", "omitted": []}}
    assert project_execution(source) == {
        **source,
        "projection": {"detail": "summary", "omitted": []},
    }


@pytest.mark.parametrize("project", [project_world, project_execution])
@pytest.mark.parametrize("detail", [None, True, 1, "", "brief", "FULL", [], {}])
def test_invalid_detail_is_rejected_without_changing_the_source(project, detail):
    source = {"nested": {"unchanged": True}}
    with pytest.raises(ValueError, match="detail"):
        project(source, detail=detail)
    assert source == {"nested": {"unchanged": True}}


def test_summary_size_reduction_on_synthetic_articulated_snapshot(world):
    service, _, _, _ = world
    snapshot = service.get_world(include_executions=True)
    full = json.dumps(project_world(snapshot, detail="full"), ensure_ascii=False).encode("utf-8")
    summary = json.dumps(project_world(snapshot), ensure_ascii=False).encode("utf-8")
    assert len(summary) < len(full)
