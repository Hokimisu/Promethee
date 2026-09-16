"""Real SQLite resume contracts; fake avatar and workers, no GPU or subprocess."""

import copy
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import body
import pytest
from body import BodyAdapter
from presence import PresenceController

from promethee.conversation import ConversationStore
from promethee.execution import ExecutionService
from promethee.initiative import Initiative
from promethee.runtime import Runtime, encode

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests"))
from test_kinematic import Worker  # noqa: E402
from test_prepared_kinematic import Preparation  # noqa: E402


@pytest.fixture
def adapter_args(tmp_path, monkeypatch):
    avatar = tmp_path / "synthetic.vrm"
    avatar.write_bytes(b"CPU test asset, never rendered")
    monkeypatch.setattr(body, "PIXIV_SHA256", hashlib.sha256(avatar.read_bytes()).hexdigest())

    def forbidden(**kwargs):
        raise AssertionError("A constructor or rejected start must not launch a worker.")

    monkeypatch.setattr(body, "start_ardy_process", forbidden)
    return {"avatar": avatar, "ardy_python": "unused", "checkpoint_root": "unused"}


def session(path, **kwargs):
    return Runtime(
        path / "world.sqlite3", data_origin="session", session_kind="qualification", **kwargs
    )


def dump(runtime):
    with runtime.connection() as conn:
        return list(conn.iterdump())


def retained_conversation_and_budget(service):
    store = ConversationStore(service)
    request = store.begin("Test de reprise.")
    store.finish(
        request["turn_id"],
        {
            "type": "result",
            "turn_id": request["turn_id"],
            "failed": False,
            "interrupted": False,
            "text": "Historique de qualification.",
            "messages": [
                {"role": "user", "content": "Test de reprise."},
                {"role": "assistant", "content": "Historique de qualification."},
            ],
        },
    )
    initiative = Initiative(service)
    initiative.configure(budget=3, interval=20)
    initiative.update(paused=True)


def test_new_world_default_and_existing_refused_without_writes(tmp_path, adapter_args):
    directory = tmp_path / "new"
    adapter = BodyAdapter(directory, **adapter_args)
    state = adapter.service.runtime.snapshot()
    assert state["data_origin"] == "session" and state["session_kind"] == "qualification"
    assert adapter.artifacts_dir == directory
    before = dump(adapter.service.runtime)
    purpose = (directory / "body-purpose.json").read_bytes()
    with pytest.raises(ValueError, match="existing worlds"):
        BodyAdapter(directory, **adapter_args)
    assert dump(adapter.service.runtime) == before
    assert (directory / "body-purpose.json").read_bytes() == purpose
    adapter.close()


@pytest.mark.parametrize("resume", [None, 0, 1, "true"])
def test_resume_must_be_boolean(tmp_path, adapter_args, resume):
    with pytest.raises(ValueError, match="resume"):
        BodyAdapter(tmp_path / "missing", resume=resume, **adapter_args)
    assert not (tmp_path / "missing").exists()


def test_resume_requires_database_and_creates_nothing(tmp_path, adapter_args):
    directory = tmp_path / "missing"
    with pytest.raises(ValueError, match="existing world.sqlite3"):
        BodyAdapter(directory, resume=True, **adapter_args)
    assert not directory.exists()


@pytest.mark.parametrize(
    "origin,kind", [("fixture", None), ("session", "interactive"), ("session", None)]
)
def test_resume_refuses_nonqualification_world_unchanged(tmp_path, adapter_args, origin, kind):
    runtime = Runtime(tmp_path / "world.sqlite3", data_origin=origin, session_kind=kind)
    before = dump(runtime)
    with pytest.raises(ValueError, match="cannot be changed"):
        BodyAdapter(tmp_path, resume=True, **adapter_args)
    assert dump(runtime) == before
    assert not (tmp_path / "body-resumes").exists()


def test_resume_refuses_old_schema_without_migration(tmp_path, adapter_args):
    runtime = session(tmp_path)
    state = runtime.snapshot()
    state["schema_version"] -= 1
    with runtime.connection() as conn:
        conn.execute("UPDATE world SET data=? WHERE id=1", (encode(state),))
    before = dump(runtime)
    with pytest.raises(ValueError, match="schema version"):
        BodyAdapter(tmp_path, resume=True, **adapter_args)
    assert dump(runtime) == before
    assert not list(tmp_path.glob("*.bak*"))
    assert not (tmp_path / "body-resumes").exists()


def test_resume_preserves_history_budget_pause_and_old_artifacts(tmp_path, adapter_args):
    runtime = session(tmp_path)
    retained_conversation_and_budget(ExecutionService(runtime))
    (tmp_path / "body-purpose.json").write_bytes(b"old provenance retained exactly")
    (tmp_path / "motions").mkdir()
    (tmp_path / "motions" / "conventions.json").write_bytes(b"previous worker conventions")
    before = dump(runtime)
    adapters = [BodyAdapter(tmp_path, resume=True, **adapter_args) for _ in range(2)]
    assert dump(runtime) == before
    assert adapters[0].artifacts_dir != adapters[1].artifacts_dir
    for adapter in adapters:
        assert adapter.data_dir == tmp_path
        assert adapter.service.runtime.create is False
        assert adapter.options["output"] == adapter.artifacts_dir / "motions"
        assert adapter.poll()["world"]["world_id"] == runtime.snapshot()["world_id"]
        assert not adapter.poll()["ready"]
        assert adapter.poll()["motion"] is None
        provenance = json.loads((adapter.artifacts_dir / "body-resume.json").read_text())
        assert provenance["resume"] is True
        assert provenance["world_id"] == runtime.snapshot()["world_id"]
        assert provenance["no_archived_motion_replay"] is True
        adapter.close()
    assert dump(runtime) == before
    assert (tmp_path / "body-purpose.json").read_bytes() == b"old provenance retained exactly"
    assert (
        tmp_path / "motions" / "conventions.json"
    ).read_bytes() == b"previous worker conventions"


def test_live_controller_owner_is_refused_before_artifacts_or_process(tmp_path, adapter_args):
    runtime = session(tmp_path)
    service = ExecutionService(runtime)
    owner = service.acquire_controller(source="kinematic", supported_actions=["move"])
    before = dump(runtime)
    try:
        with pytest.raises(ValueError, match="already owns"):
            BodyAdapter(tmp_path, resume=True, **adapter_args)
        assert dump(runtime) == before
        assert not (tmp_path / "body-resumes").exists()
    finally:
        owner.release()


def test_owner_acquired_after_open_is_rejected_by_start(tmp_path, adapter_args):
    runtime = session(tmp_path)
    adapter = BodyAdapter(tmp_path, resume=True, **adapter_args)
    owner = ExecutionService(runtime).acquire_controller(
        source="kinematic", supported_actions=["move"]
    )
    before = dump(runtime)
    try:
        with pytest.raises(ValueError, match="already owns"):
            adapter.start()
        assert adapter._thread is None
        assert dump(runtime) == before
    finally:
        owner.release()
        adapter.close()


def test_expired_owner_is_not_recovered_until_existing_controller_acquires(tmp_path, adapter_args):
    runtime = session(tmp_path)
    old_service = ExecutionService(runtime, clock=lambda: 1000.0)
    retained_conversation_and_budget(old_service)
    old = old_service.acquire_controller(source="kinematic", supported_actions=["move"])
    state = runtime.snapshot()
    observation = {key: copy.deepcopy(state[key]) for key in ("avatar", "objects", "pose")}
    observation["pose"] = {
        "skeleton": "cskel27",
        "positions": [[0.0, 1.0, 0.0] for _ in range(27)],
        "rotations": [[[1, 0, 0], [0, 1, 0], [0, 0, 1]] for _ in range(27)],
    }
    assert old.reconcile(observation, stopped=True)
    old_service.submit(
        "old-move",
        old_service.get_world()["revision"],
        {"kind": "move", "args": {"position": [0.5, 0.0]}},
    )
    before = dump(runtime)
    adapter = BodyAdapter(tmp_path, resume=True, **adapter_args)
    assert dump(runtime) == before  # No get_world expiry while merely opening.
    initiative = runtime.snapshot()["initiative"]
    with runtime.connection() as conn:
        history = conn.execute("SELECT * FROM conversation_turns").fetchall()
    output = adapter.options["output"]
    output.mkdir()
    worker, preparation = Worker(output), Preparation()
    controller = PresenceController(
        adapter.service, worker, continuous_motion=True, appearance_preparation=preparation
    )
    try:
        assert adapter.service.get("old-move")["status"] == "interrupted"
        assert adapter.service.get("old-move")["error"]["code"] == "controller_lost"
        assert runtime.snapshot()["body"]["status"] == "unconfirmed"
        controller.tick()
        assert not controller.ready  # Existing pose still requires prepared appearance.
        assert not worker.jobs  # No archived clip or replacement motion is generated.
        preparation.finish()
        controller.tick()
        assert controller.ready
        assert runtime.snapshot()["pose"] == observation["pose"]
        assert runtime.snapshot()["body"]["status"] == "confirmed"
        assert runtime.snapshot()["initiative"] == initiative
        with runtime.connection() as conn:
            assert conn.execute("SELECT * FROM conversation_turns").fetchall() == history
    finally:
        controller.close()
        adapter.close()
    # A subsequent prepared checkpoint restores directly through the same controller.
    resumed = BodyAdapter(tmp_path, resume=True, **adapter_args)
    checkpoint = runtime.snapshot()
    resumed.options["output"].mkdir()
    worker, preparation = Worker(resumed.options["output"]), Preparation()
    controller = PresenceController(
        resumed.service, worker, continuous_motion=True, appearance_preparation=preparation
    )
    try:
        controller.tick()
        assert controller.ready and not worker.jobs and not preparation.jobs
        restored = runtime.snapshot()
        for field in ("world_id", "pose", "appearance", "initiative"):
            assert restored[field] == checkpoint[field]
    finally:
        controller.close()
        resumed.close()


def test_motion_bone_indices_are_stable_across_sorted_checkpoint_and_native_pose(
    tmp_path, adapter_args
):
    adapter = BodyAdapter(tmp_path / "world", **adapter_args)
    rotations = {"hips": [0.0, 0.0, 0.0, 1.0], "head": [0.0, 0.6, 0.0, 0.8]}
    restored = json.loads(encode(rotations))
    assert list(restored) != list(rotations)  # Actual SQLite serialization changes order.
    controller = SimpleNamespace(
        ready=True,
        handle=SimpleNamespace(session_id="same-controller"),
        message="Synthetic CPU publication",
        presence_enabled=False,
        presence_status="disabled",
        presence_error=None,
    )

    class Publisher:
        bootstrap = None
        sequence = 0

        def update(self, _controller):
            self.sequence += 1
            self.latest = json.dumps(
                {
                    "sequence": self.sequence,
                    "observation": {
                        "pose": {"positions": [[0.0, 1.0, 0.0]]},
                        "appearance": {"frame": {"root_y_offset": 0.0, "rotations": self.names}},
                    },
                }
            )

    publisher = Publisher()
    motions = []
    try:
        # Resume checkpoint first, then a fresh prepared pose in the same stream.
        for values in (restored, rotations):
            publisher.names = values
            adapter._publish(controller, publisher)
            motions.append(adapter.poll()["motion"])
        assert motions[0]["id"] == motions[1]["id"] == "same-controller"
        assert motions[0]["bone_names"] == motions[1]["bone_names"] == sorted(rotations)
        assert motions[0]["frames"] == motions[1]["frames"]
        for motion in motions:
            assert (
                dict(zip(motion["bone_names"], motion["frames"][0]["rotations"], strict=True))
                == rotations
            )
    finally:
        adapter.close()
