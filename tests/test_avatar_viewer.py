import hashlib
import http.client
import json
import threading

import pytest

from promethee import avatar_viewer


def test_viewer_serves_only_declared_files_and_no_mutations(tmp_path, monkeypatch):
    model = tmp_path / "avatar.vrm"
    model.write_bytes(b"local transport fixture, not a VRM qualification")
    monkeypatch.setattr(
        avatar_viewer, "PIXIV_SHA256", hashlib.sha256(model.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(avatar_viewer, "motion_document", lambda *_: {"frames": []})
    for name in ("index.html", "style.css", "app.js", "app.js.LEGAL.txt"):
        (tmp_path / name).write_text(name)
    with avatar_viewer.create_server(
        web_root=tmp_path, avatar=model, motion=None, skeleton=None, port=0
    ) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            for method, path, headers, status in (
                ("GET", "/motion.json", {}, 200),
                ("GET", "/../avatar.vrm", {}, 404),
                ("GET", "/", {"Host": "unrelated.example"}, 403),
                ("POST", "/actions", {}, 501),
            ):
                conn.request(method, path, headers=headers)
                response = conn.getresponse()
                assert response.status == status
                response.read()
            conn.close()
        finally:
            server.shutdown()
            thread.join(timeout=2)


def test_viewer_rejects_a_different_asset_before_serving(tmp_path):
    model = tmp_path / "other.vrm"
    model.write_bytes(b"unqualified asset")
    with pytest.raises(ValueError, match="fingerprint"):
        avatar_viewer.create_server(web_root=tmp_path, avatar=model, motion=None, skeleton=None)


def test_object_replay_requires_matching_pose_and_known_visual(
    tmp_path, monkeypatch, articulated_pose
):
    np = pytest.importorskip("numpy")
    monkeypatch.setattr(avatar_viewer, "load_skeleton", lambda _: {})
    motion = tmp_path / "motion.npz"
    np.savez(
        motion,
        posed_joints=[articulated_pose["positions"]],
        global_rot_mats=[articulated_pose["rotations"]],
        fps=20.0,
    )
    obj = {
        "asset": "plush",
        "position": [0, 0],
        "spatial": {
            "position": [0, 0.5, 0],
            "rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "attachment": None,
        },
    }
    observation = {
        "pose": articulated_pose,
        "objects": {"item": obj},
        "avatar": {"position": [0, 0], "holding": None, "seated_on": None},
    }
    path = tmp_path / "objects.json"

    def save():
        path.write_text(json.dumps([observation]), encoding="utf-8")

    save()
    document = avatar_viewer.motion_document(motion, None, path)
    assert document["objects"] == [{"item": obj}]
    assert "plush" in document["object_models"]
    observation["pose"]["positions"][10][0] += 0.1
    save()
    with pytest.raises(ValueError, match="poses disagree"):
        avatar_viewer.motion_document(motion, None, path)
    observation["pose"]["positions"][10][0] -= 0.1
    obj["asset"] = "bed"
    save()
    with pytest.raises(ValueError, match="known visual"):
        avatar_viewer.motion_document(motion, None, path)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="one complete observation"):
        avatar_viewer.motion_document(motion, None, path)
