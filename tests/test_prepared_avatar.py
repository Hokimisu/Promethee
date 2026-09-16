"""Analytic appearance records; actual asset replay is qualified separately."""

import copy
import hashlib
import json
import math

import pytest
from test_avatar_reach import example

from promethee.avatar_rotation import normalized_core_rotation, quaternion_matrix
from promethee.prepared_avatar import EXTRA_BONES, load_prepared_poses

np = pytest.importorskip("numpy")


def record():
    reach, skeleton, pose, _ = example()
    profile = reach.profile
    rotations = {n: [0, 0, 0, 1] for n in set(profile["bones"]) | set(EXTRA_BONES)}
    rotations["rightLowerArm"] = [0, math.sin(0.35), 0, math.cos(0.35)]
    upper = (
        np.asarray(pose["positions"][0])
        + (
            np.array(profile["bones"]["rightUpperArm"]["rest_position"])
            - profile["bones"]["hips"]["rest_position"]
        )
        * profile["scale"]
        + [0, -0.02, 0]
    )
    rest = profile["bones"]
    elbow = (
        upper
        + (
            np.array(rest["rightLowerArm"]["rest_position"])
            - rest["rightUpperArm"]["rest_position"]
        )
        * profile["scale"]
    )
    yaw = np.array(
        [[math.cos(0.7), 0, math.sin(0.7)], [0, 1, 0], [-math.sin(0.7), 0, math.cos(0.7)]]
    )
    pose["positions"][10] = (
        elbow
        + yaw
        @ (np.array(rest["rightHand"]["rest_position"]) - rest["rightLowerArm"]["rest_position"])
        * profile["scale"]
    ).tolist()
    document = {
        "fps": 20,
        "avatar_profile": profile,
        "skeleton": skeleton,
        "frames": [pose, copy.deepcopy(pose)],
        "objects": [{"item": {"spatial": {"attachment": {"joint": "RightHand"}}}}] * 2,
    }
    payload = json.dumps(document).encode()
    artifact = {
        "version": 1,
        "avatar_sha256": profile["asset_sha256"],
        "motion_sha256": hashlib.sha256(payload).hexdigest(),
        "scale": profile["scale"],
        "mode": "--settle",
        "aligned_hands": ["RightHand"],
        "frames": [{"root_y_offset": -0.02, "rotations": rotations}] * 2,
    }
    return payload, artifact


def test_prepared_record_matches_source_and_returns_independent_data(tmp_path):
    payload, artifact = record()
    path = tmp_path / "poses.json"
    path.write_text(json.dumps(artifact))
    accepted = load_prepared_poses(path, payload)
    assert accepted == artifact
    accepted["frames"][0]["rotations"]["hips"][0] = 1
    assert load_prepared_poses(path, payload) == artifact
    with pytest.raises(ValueError, match="provenance"):
        load_prepared_poses(path, payload + b" ")


@pytest.mark.parametrize("change", [None, "flag", "pose", "offset", "rotation", "count"])
def test_continuous_preparation_requires_exact_origin(tmp_path, change):
    from promethee.appearance_checkpoint import appearance_checkpoint

    payload, artifact = record()
    document = json.loads(payload)
    artifact.update(
        version=2,
        frame_alignment_weights=[{"RightHand": 1.0, "LeftHand": 0.0}] * 41,
    )
    document.update(
        observed_origin=True,
        initial_pose=copy.deepcopy(document["frames"][0]),
        initial_appearance=appearance_checkpoint(artifact, 0, document["frames"][0]),
        frames=[copy.deepcopy(document["frames"][0]) for _ in range(41)],
        objects=[copy.deepcopy(document["objects"][0]) for _ in range(41)],
    )
    artifact["frames"] = [copy.deepcopy(artifact["frames"][0]) for _ in range(41)]
    if change == "flag":
        document["observed_origin"] = 1
    if change == "pose":
        document["frames"][0]["positions"][0][0] += 1e-10
    if change == "offset":
        artifact["frames"][0]["root_y_offset"] += 1e-10
    if change == "rotation":
        artifact["frames"][0]["rotations"]["leftFoot"][0] += 1e-10
    if change == "count":
        document["frames"].pop()
        document["objects"].pop()
        artifact["frames"].pop()
        artifact["frame_alignment_weights"].pop()
    payload = json.dumps(document).encode()
    artifact["motion_sha256"] = hashlib.sha256(payload).hexdigest()
    path = tmp_path / "poses.json"
    path.write_text(json.dumps(artifact))
    if change is None:
        assert load_prepared_poses(path, payload) == artifact
    else:
        with pytest.raises(ValueError, match="exact observed origin"):
            load_prepared_poses(path, payload)


@pytest.mark.parametrize(
    "change",
    [
        None,
        "flag",
        "missing_origin",
        "source_leg",
        "source_root",
        "source_rotation",
        "foot",
        "offset",
        "first_arm",
    ],
)
def test_stationary_interaction_preserves_prepared_support_and_exact_origin(tmp_path, change):
    from promethee.appearance_checkpoint import appearance_checkpoint

    payload, artifact = record()
    document = json.loads(payload)
    artifact = copy.deepcopy(artifact)
    artifact["frames"] = [copy.deepcopy(frame) for frame in artifact["frames"]]
    # Represent prior planting: the prepared leg differs from its raw Core rotation.
    for frame in artifact["frames"]:
        frame["rotations"]["leftLowerLeg"] = [math.sin(0.05), 0, 0, math.cos(0.05)]
    artifact.update(
        version=2,
        frame_alignment_weights=[{"RightHand": 1.0, "LeftHand": 0.0}] * 2,
    )
    document.update(
        stationary_support=True,
        initial_pose=copy.deepcopy(document["frames"][0]),
        initial_appearance=appearance_checkpoint(artifact, 0, document["frames"][0]),
    )
    if change == "flag":
        document["stationary_support"] = 1
    if change == "missing_origin":
        del document["initial_appearance"]
    if change in {"source_leg", "source_root"}:
        joint = document["skeleton"]["joint_names"].index(
            "LeftFoot" if change == "source_leg" else "Hips"
        )
        document["frames"][1]["positions"][joint][0] += 0.001
    if change == "source_rotation":
        joint = document["skeleton"]["joint_names"].index("LeftUpLeg")
        document["frames"][1]["rotations"][joint] = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]
    if change == "foot":
        artifact["frames"][1]["rotations"]["leftLowerLeg"] = [0, 0, 0, 1]
    if change == "offset":
        artifact["frames"][1]["root_y_offset"] += 1e-8
    if change == "first_arm":
        artifact["frames"][0]["rotations"]["rightLowerArm"] = [0, 0, 0, 1]
    payload = json.dumps(document).encode()
    artifact["motion_sha256"] = hashlib.sha256(payload).hexdigest()
    path = tmp_path / "poses.json"
    path.write_text(json.dumps(artifact))
    if change is None:
        assert load_prepared_poses(path, payload) == artifact
        del document["stationary_support"]
        payload = json.dumps(document).encode()
        artifact["motion_sha256"] = hashlib.sha256(payload).hexdigest()
        path.write_text(json.dumps(artifact))
        with pytest.raises(ValueError, match="unadapted Core rotation"):
            load_prepared_poses(path, payload)
    else:
        with pytest.raises(ValueError, match="Stationary support"):
            load_prepared_poses(path, payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", True),
        ("avatar_sha256", "0" * 64),
        ("scale", 1.0),
        ("mode", "none"),
        ("mode", "--plant"),
        ("aligned_hands", []),
        ("aligned_hands", ["RightHand", "RightHand"]),
        ("frames", []),
    ],
)
def test_wrong_identity_or_incomplete_appearance_is_refused(tmp_path, field, value):
    payload, artifact = record()
    artifact[field] = value
    path = tmp_path / "poses.json"
    path.write_text(json.dumps(artifact))
    with pytest.raises(ValueError):
        load_prepared_poses(path, payload)


@pytest.mark.parametrize(
    "corruption", ["root", "step", "nan", "quaternion", "bone", "torso", "wrist", "leg"]
)
def test_pose_tampering_cannot_change_the_observed_hand_or_torso(tmp_path, corruption):
    payload, artifact = record()
    artifact = copy.deepcopy(artifact)
    # Break the fixture's shared frame deliberately to test a transition.
    artifact["frames"][1] = copy.deepcopy(artifact["frames"][0])
    frame = artifact["frames"][1]
    if corruption == "root":
        frame["root_y_offset"] = -0.051
    if corruption == "step":
        frame["root_y_offset"] = 0.001
    if corruption == "nan":
        frame["root_y_offset"] = float("nan")
    if corruption == "quaternion":
        frame["rotations"]["rightHand"] = [0, 0, 0, 2]
    if corruption == "bone":
        del frame["rotations"]["leftFoot"]
    if corruption == "torso":
        frame["rotations"]["spine"] = [0, 0, 1, 0]
    if corruption == "wrist":
        frame["rotations"]["rightLowerArm"] = [0, 0, 0, 1]
    if corruption == "leg":
        frame["rotations"]["rightFoot"] = [0, 1, 0, 0]
    path = tmp_path / "poses.json"
    path.write_text(json.dumps(artifact))
    with pytest.raises(ValueError):
        load_prepared_poses(path, payload)


@pytest.mark.parametrize(
    "matrix",
    [
        [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        [[1, 0, 0], [0, -1, 0], [0, 0, -1]],
        [[-1, 0, 0], [0, 1, 0], [0, 0, -1]],
        [[-1, 0, 0], [0, -1, 0], [0, 0, 1]],
        [[0, 0, 1], [0, 1, 0], [-1, 0, 0]],
    ],
)
def test_rotation_conversion_preserves_half_turns_and_yaw(matrix):
    np.testing.assert_allclose(normalized_core_rotation(matrix), matrix, atol=1e-15)


def test_imperfect_core_matrix_uses_the_measured_three_conversion():
    matrix = [
        [-0.7069067811865475, -0.7071067811865476, 0],
        [0.7071067811865476, -0.7071067811865475, 0],
        [0, 0, 1],
    ]
    # Captured from rotationQuaternion in the pinned web renderer, not from SVD.
    expected = quaternion_matrix([0, 0, 0.9238716062834372, 0.3827025674113796])
    np.testing.assert_allclose(normalized_core_rotation(matrix), expected, atol=1e-15)
    u, _, vt = np.linalg.svd(matrix)
    assert np.max(abs(expected - u @ vt)) > 1e-5


@pytest.mark.parametrize("invalid", [False, True])
def test_version_two_weights_must_match_the_requested_alignment(tmp_path, invalid):
    payload, artifact = record()
    artifact.update(
        version=2,
        frame_alignment_weights=[{"RightHand": 1.0, "LeftHand": 0.0} for _ in artifact["frames"]],
    )
    if invalid:
        artifact["frame_alignment_weights"][0]["RightHand"] = 0.4
    path = tmp_path / "poses.json"
    path.write_text(json.dumps(artifact))
    if invalid:
        with pytest.raises(ValueError, match="transition differs"):
            load_prepared_poses(path, payload)
    else:
        assert load_prepared_poses(path, payload) == artifact
