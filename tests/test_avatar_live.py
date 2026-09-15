"""Local HTTP transport with analytic body fixtures, not an avatar/model qualification."""

import hashlib
import http.client
import json

import pytest
from test_object_actions import advance, spawn
from test_object_actions import objects as objects

from promethee.avatar_live import AvatarLiveServer


@pytest.fixture
def live(objects, tmp_path, monkeypatch):
    model = tmp_path / "avatar.vrm"
    model.write_bytes(b"explicit HTTP test asset, never rendered")
    monkeypatch.setattr(
        "promethee.avatar_live.PIXIV_SHA256", hashlib.sha256(model.read_bytes()).hexdigest()
    )
    web = tmp_path / "web"
    web.mkdir()
    for name in ("index.html", "style.css", "app.js", "app.js.LEGAL.txt"):
        (web / name).write_text("test", encoding="utf-8")
    now = [10.0]
    server = AvatarLiveServer(objects[1], avatar=model, web_root=web, port=0, clock=lambda: now[0])
    server.update(objects[0])
    try:
        yield server, objects, now
    finally:
        server.stop()


def request(server, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=3)
    values = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{server.port}"}
    values.update(headers or {})
    try:
        connection.request(
            method, path, body=json.dumps(body) if body is not None else None, headers=values
        )
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def test_snapshot_is_immutable_until_the_body_loop_publishes_again(live):
    server, state, _ = live
    status, first = request(server, "GET", "/state.json")
    assert status == 200
    state[0].observation["pose"]["positions"][10][0] += 0.01
    assert request(server, "GET", "/state.json")[1] == first
    server.update(state[0])
    second = request(server, "GET", "/state.json")[1]
    assert second["sequence"] == first["sequence"] + 1
    assert second["observation"] == state[0].observation
    assert second["observation"] != first["observation"]


def test_http_actions_use_durable_execution_and_retransmission(live):
    server, state, _ = live
    envelope = {
        "request_id": "http-spawn",
        "expected_revision": state[1].get_world()["revision"],
        "action": {
            "kind": "spawn",
            "args": {"object_id": "item", "asset": "ball", "position": [0, 1.3, 0.25]},
        },
    }
    status, item = request(server, "POST", "/action", envelope)
    assert status == 200 and item["status"] == "accepted"
    assert state[1].get_world()["objects"] == {}
    state[0].tick()
    advance(state, 0.1)
    server.update(state[0])
    before = state[1].get_world()
    repeated = request(server, "POST", "/action", envelope)[1]
    assert repeated["status"] == "completed"
    assert state[1].get_world() == before
    assert request(server, "GET", "/execution/http-spawn")[1]["status"] == "completed"
    assert request(server, "GET", "/state.json")[1]["observation"]["objects"] == before["objects"]


def test_http_cancel_before_dispatch_never_starts_motion(live):
    server, state, _ = live
    envelope = {
        "request_id": "cancel-before-start",
        "expected_revision": state[1].get_world()["revision"],
        "action": {
            "kind": "spawn",
            "args": {"object_id": "item", "asset": "ball", "position": [0, 1.3, 0.25]},
        },
    }
    request(server, "POST", "/action", envelope)
    _, item = request(server, "POST", "/cancel", {"request_id": "cancel-before-start"})
    # Cancellation before dispatch is terminal without a body motion.
    assert item["status"] == "cancelled"
    state[0].tick()
    assert state[1].get_world()["objects"] == {}


@pytest.mark.parametrize("when,holding", [(1.0, None), (3.5, "item")])
def test_running_http_cancel_waits_for_body_and_preserves_contact(live, when, holding):
    server, state, _ = live
    spawn(state, asset="ball")
    envelope = {
        "request_id": "http-take",
        "expected_revision": state[1].get_world()["revision"],
        "action": {"kind": "take", "args": {"object_id": "item"}},
    }
    request(server, "POST", "/action", envelope)
    state[0].tick()
    advance(state, when)
    server.update(state[0])
    before = request(server, "GET", "/state.json")[1]["observation"]
    _, item = request(server, "POST", "/cancel", {"request_id": "http-take"})
    assert item["status"] == "running"
    assert item["cancel_requested"]
    state[0].tick()
    server.update(state[0])
    snapshot = request(server, "GET", "/state.json")[1]
    assert snapshot["execution"]["status"] == "cancelled"
    assert snapshot["observation"] == before
    assert snapshot["observation"]["avatar"]["holding"] == holding


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://other.example"},
        {"Host": "other.example"},
        {"Content-Type": "text/plain"},
        {"Content-Length": "20000"},
    ],
)
def test_untrusted_or_unbounded_post_cannot_modify_world(live, headers):
    server, state, _ = live
    before = state[1].get_world()
    status, _ = request(server, "POST", "/action", {}, headers)
    assert status in {400, 403}
    assert state[1].get_world() == before


def test_stale_stream_and_arbitrary_routes_are_refused(live):
    server, _, now = live
    assert request(server, "GET", "/motion.json")[1]["mode"] == "live"
    now[0] += 1.1
    assert request(server, "GET", "/state.json")[0] == 503
    assert request(server, "GET", "/../world.sqlite3")[0] == 404
    assert request(server, "GET", "/state.json", headers={"Host": "other.example"})[0] == 403
