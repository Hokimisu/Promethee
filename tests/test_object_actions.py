"""Controller qualification with analytic poses; these fixtures are not model trials."""

import copy

import pytest
from test_arm_reach import fixture as arm_fixture
from test_kinematic import Worker

from promethee.execution import ExecutionService
from promethee.kinematic import KinematicController
from promethee.object_actions import bounds, check_clearance
from promethee.runtime import Runtime

np = pytest.importorskip("numpy")


@pytest.fixture
def objects(tmp_path):
    skeleton, pose = arm_fixture()
    now = [100.0]
    service = ExecutionService(
        Runtime(tmp_path / "world.sqlite3", data_origin="session", session_kind="qualification"),
        clock=lambda: now[0],
    )
    handle = service.acquire_controller(source="kinematic", supported_actions=["move"])
    handle.reconcile(
        {
            "pose": pose,
            "objects": {},
            "avatar": {"position": [0.0, 0.0], "holding": None, "seated_on": None},
        },
        stopped=True,
    )
    handle.release()
    worker = Worker(tmp_path)
    worker.messages[0]["skeleton"] = skeleton
    controller = KinematicController(
        service, worker, clock=lambda: now[0], object_interactions=True
    )
    controller.tick()
    yield controller, service, worker, now, skeleton
    controller.close()


def command(state, rid, kind, args):
    controller, service, _, _, _ = state
    item = service.submit(rid, service.get_world()["revision"], {"kind": kind, "args": args})
    controller.tick()
    return item


def advance(state, seconds):
    controller, _, _, now, _ = state
    for _ in range(round(seconds / 0.05)):
        now[0] += 0.05
        controller.tick()


def spawn(state, rid="spawn", point=None, asset="plush"):
    command(
        state,
        rid,
        "spawn",
        {"object_id": "item", "asset": asset, "position": point or [0, 1.3, 0.25]},
    )
    advance(state, 0.1)
    assert state[1].get(rid)["status"] == "completed"


@pytest.mark.parametrize("asset", ["plush", "ball"])
def test_take_attaches_only_at_contact_and_place_releases_only_at_arrival(objects, asset):
    controller, service, worker, _, _ = objects
    spawn(objects, asset=asset)
    original = copy.deepcopy(service.get_world()["objects"]["item"])
    assert command(objects, "take", "take", {"object_id": "item"})["status"] == "accepted"
    assert service.get("take")["status"] == "running"
    advance(objects, 1.0)
    assert service.get_world()["avatar"]["holding"] is None
    assert service.get_world()["objects"]["item"] == original
    advance(objects, 2.1)
    assert service.get_world()["avatar"]["holding"] == "item"
    assert service.get("take")["status"] == "running"
    advance(objects, 1.5)
    assert service.get("take")["status"] == "completed"
    assert command(objects, "occupied", "take", {"object_id": "item"})["status"] == "rejected"
    assert service.get_world()["objects"]["item"]["spatial"]["position"][1] == pytest.approx(1.36)
    command(objects, "place", "place", {"position": [0, 1.27, 0.27]})
    advance(objects, 1.0)
    assert service.get_world()["avatar"]["holding"] == "item"
    advance(objects, 2.1)
    assert service.get("place")["status"] == "completed"
    assert service.get_world()["avatar"]["holding"] is None
    assert service.get_world()["objects"]["item"]["spatial"]["position"] == pytest.approx(
        [0, 1.27, 0.27]
    )
    assert worker.jobs == []
    check_clearance(controller.observation)


@pytest.mark.parametrize("when,holding", [(1.0, None), (3.5, "item")])
@pytest.mark.parametrize("asset", ["plush", "ball"])
def test_cancel_and_restart_keep_the_actual_attachment_state(objects, when, holding, asset):
    controller, service, worker, now, skeleton = objects
    spawn(objects, asset=asset)
    command(objects, "take", "take", {"object_id": "item"})
    advance(objects, when)
    expected = copy.deepcopy(controller.observation)
    service.cancel("take")
    controller.tick()
    assert service.get("take")["status"] == "cancelled"
    assert service.get_world()["avatar"]["holding"] == holding
    controller.close()
    replacement_worker = Worker(worker.output)
    replacement_worker.messages[0]["skeleton"] = skeleton
    replacement = KinematicController(
        service, replacement_worker, clock=lambda: now[0], object_interactions=True
    )
    try:
        replacement.tick()
        assert replacement.observation == expected
        assert replacement_worker.jobs == []
        assert replacement.handle.claim_next() is None
    finally:
        replacement.close()


def test_moved_target_is_not_overwritten_by_the_precomputed_approach(objects):
    controller, service, _, _, _ = objects
    spawn(objects)
    command(objects, "take", "take", {"object_id": "item"})
    advance(objects, 0.5)
    obj = controller.observation["objects"]["item"]
    obj["spatial"]["position"][2] += 0.3
    obj["position"][1] += 0.3
    changed = copy.deepcopy(obj)
    controller.tick()
    assert service.get("take")["status"] == "failed"
    assert service.get_world()["objects"]["item"] == changed
    assert service.get_world()["avatar"]["holding"] is None


@pytest.mark.parametrize("point", [[0, 0, 0.3], [0, 1.3, 0]])
def test_spawn_refuses_floor_and_body_intersections(objects, point):
    command(objects, "bad", "spawn", {"object_id": "item", "asset": "plush", "position": point})
    advance(objects, 0.1)
    assert objects[1].get("bad")["status"] == "failed"
    assert objects[1].get_world()["objects"] == {}


def test_unreachable_target_does_not_create_success(objects):
    spawn(objects, point=[0, 0.2, 0.3])
    command(objects, "unreachable", "take", {"object_id": "item"})
    assert objects[1].get("unreachable")["status"] == "failed"
    assert objects[1].get_world()["avatar"]["holding"] is None


def test_ellipsoid_bounds_rotate_with_object():
    obj = {
        "asset": "plush",
        "spatial": {"position": [1, 1, 1], "rotation": [[0, 0, 1], [0, 1, 0], [-1, 0, 0]]},
    }
    low, high = bounds(obj)
    np.testing.assert_allclose(high - low, [0.1, 0.224, 0.164], atol=1e-10)


@pytest.mark.parametrize("asset", ["plush", "ball"])
def test_live_mesh_has_outward_faces_and_matching_dimensions(asset):
    from promethee.object_models import OBJECT_MODELS, part_mesh

    for part in OBJECT_MODELS[asset]:
        vertices, faces = part_mesh(part)
        triangles = vertices[faces]
        normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
        outward = triangles.mean(axis=1) - part["center"]
        assert np.all(np.einsum("ij,ij->i", normals, outward) >= -1e-12)
        np.testing.assert_allclose(vertices.max(0) - vertices.min(0), part["size"], atol=1e-8)


def test_clearance_requires_observed_body_pose():
    with pytest.raises(ValueError, match="observed articulated"):
        check_clearance({"pose": None, "objects": {}})


def test_contact_points_lie_on_their_visual_surface():
    from promethee.object_models import CONTACT_POINTS, OBJECT_MODELS

    for asset, contacts in CONTACT_POINTS.items():
        for point in contacts.values():
            distances = [
                np.linalg.norm(
                    (np.asarray(point) - part["center"]) / (np.asarray(part["size"]) / 2)
                )
                for part in OBJECT_MODELS[asset]
            ]
            assert min(distances) == pytest.approx(1.0)


def test_second_geometry_cannot_spawn_over_existing_object(objects):
    spawn(objects)
    before = copy.deepcopy(objects[1].get_world()["objects"])
    command(
        objects,
        "overlap",
        "spawn",
        {"object_id": "ball", "asset": "ball", "position": [0, 1.3, 0.25]},
    )
    assert objects[1].get("overlap")["status"] == "failed"
    assert objects[1].get_world()["objects"] == before
