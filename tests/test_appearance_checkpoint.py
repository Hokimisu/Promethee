"""Storage/transaction fixtures only, with no claim of plausible geometry."""

import copy
import json
import sqlite3
import subprocess
import sys

import pytest
from conftest import Clock

from promethee.appearance_checkpoint import appearance_checkpoint
from promethee.avatar_reach import load_profile
from promethee.execution import ExecutionService
from promethee.prepared_avatar import EXTRA_BONES
from promethee.runtime import Runtime
from promethee.spatial import attachment_transform
from promethee.world import ActionError, validate_observation


def observed(pose):
    profile = load_profile()
    artifact = {
        "version": 1,
        "avatar_sha256": profile["asset_sha256"],
        "scale": profile["scale"],
        "mode": "--settle",
        "aligned_hands": [],
        "frames": [
            {
                "root_y_offset": -0.02,
                "rotations": {
                    name: [0, 0, 0, 1] for name in set(profile["bones"]) | set(EXTRA_BONES)
                },
            }
        ],
    }
    return {
        "avatar": {
            "position": [pose["positions"][0][0], pose["positions"][0][2]],
            "holding": None,
            "seated_on": None,
        },
        "objects": {},
        "pose": copy.deepcopy(pose),
        "appearance": appearance_checkpoint(artifact, 0, pose),
    }


@pytest.fixture
def prepared_body(tmp_path, articulated_pose):
    service = ExecutionService(
        Runtime(tmp_path / "world.sqlite3", data_origin="session"), clock=Clock()
    )
    driver = service.acquire_controller(source="kinematic", supported_actions=["move"])
    observation = observed(articulated_pose)
    assert driver.reconcile(observation, stopped=True)
    return service, driver, observation


@pytest.mark.parametrize(
    "defect", ["pose", "avatar", "height", "bone", "rotation", "missing", "null"]
)
def test_inconsistent_appearance_cannot_overwrite_a_confirmed_checkpoint(prepared_body, defect):
    service, driver, observation = prepared_body
    before = service.get_world()
    candidate = copy.deepcopy(observation)
    if defect == "pose":
        candidate["pose"]["positions"][3][1] += 0.01
    if defect == "avatar":
        candidate["appearance"]["avatar_sha256"] = "0" * 64
    if defect == "height":
        candidate["appearance"]["frame"]["root_y_offset"] = 0.051
    if defect == "bone":
        del candidate["appearance"]["frame"]["rotations"]["hips"]
    if defect == "rotation":
        candidate["appearance"]["frame"]["rotations"]["hips"] = [0, 0, 0, True]
    if defect == "missing":
        del candidate["appearance"]
    if defect == "null":
        candidate["appearance"] = None
    with pytest.raises(ActionError):
        driver.reconcile(candidate, stopped=True)
    assert service.get_world() == before


def test_cancel_and_reopen_preserve_the_exact_visible_checkpoint(prepared_body):
    service, driver, observation = prepared_body
    service.submit(
        "move", service.get_world()["revision"], {"kind": "move", "args": {"position": [1, 0]}}
    )
    assert driver.claim_next()["request_id"] == "move"
    assert driver.feedback("move", 0, "running", observation=observation)
    pose = copy.deepcopy(observation["pose"])
    for point in pose["positions"]:
        point[0] += 0.2
    progress = observed(pose)
    assert driver.feedback("move", 1, "running", observation=progress)
    service.cancel("move")
    assert driver.claim_cancellation()["request_id"] == "move"
    assert driver.feedback("move", 2, "cancelled", observation=progress)
    assert service.get("move")["observation"] == progress
    assert service.events()[-1]["execution"]["observation"] == progress
    driver.release()
    reopened = ExecutionService(Runtime(service.runtime.path), clock=service.clock)
    world = reopened.get_world()
    assert {key: world[key] for key in progress} == progress
    replacement = reopened.acquire_controller(source="kinematic", supported_actions=["move"])
    assert replacement.reconcile(progress, stopped=True)
    assert replacement.claim_next() is None
    assert reopened.get("move")["status"] == "cancelled"


def test_appearance_core_and_execution_event_roll_back_together(prepared_body):
    service, driver, observation = prepared_body
    service.submit(
        "move", service.get_world()["revision"], {"kind": "move", "args": {"position": [1, 0]}}
    )
    driver.claim_next()
    assert driver.feedback("move", 0, "running", observation=observation)
    before, events, execution = service.get_world(), service.events(), service.get("move")
    candidate = copy.deepcopy(observation)
    candidate["appearance"]["frame"]["root_y_offset"] -= 0.001
    with service.runtime.connection() as conn:
        conn.execute(
            "CREATE TRIGGER fail_event BEFORE INSERT ON execution_events "
            "BEGIN SELECT RAISE(ABORT, 'rollback appearance'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="rollback appearance"):
        driver.feedback("move", 1, "completed", observation=candidate)
    assert service.get_world() == before
    assert service.events() == events
    assert service.get("move") == execution


def test_checkpoint_validation_requires_no_numpy(tmp_path, articulated_pose):
    path = tmp_path / "observation.json"
    observation = observed(articulated_pose)
    path.write_text(json.dumps(observation))
    checked = validate_observation(observation)
    checked["appearance"]["frame"]["root_y_offset"] = 0
    assert observation["appearance"]["frame"]["root_y_offset"] == -0.02
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys,json; sys.modules['numpy']=None; "
            "from promethee.world import validate_observation; from pathlib import Path; "
            "validate_observation(json.loads(Path(sys.argv[1]).read_text()))",
            str(path),
        ],
        check=True,
        timeout=10,
    )


def test_held_hand_must_be_aligned_in_the_visible_checkpoint(articulated_pose):
    observation = observed(articulated_pose)
    attachment = {
        "joint": "RightHand",
        "position": [0, 0, 0],
        "rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    }
    observation["avatar"]["holding"] = "item"
    observation["objects"]["item"] = {
        "asset": "plush",
        "position": [0, 0],
        "spatial": {
            **attachment_transform(attachment, observation["pose"]),
            "attachment": attachment,
        },
    }
    with pytest.raises(ActionError, match="missing from the appearance"):
        validate_observation(observation)
    observation["appearance"]["aligned_hands"] = ["RightHand"]
    assert validate_observation(observation) == observation


def test_partial_alignment_is_preserved_without_claiming_a_fully_aligned_hand(articulated_pose):
    observation = observed(articulated_pose)
    value = observation["appearance"]
    value.update(version=2, alignment_weights={"RightHand": 0.4, "LeftHand": 0})
    assert validate_observation(observation)["appearance"]["alignment_weights"]["RightHand"] == 0.4
    value["aligned_hands"] = ["RightHand"]
    with pytest.raises(ActionError, match="alignment weights"):
        validate_observation(observation)
