import hashlib
import http.client
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
