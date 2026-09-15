"""Local VRM session transport; the existing controller remains the only body writer."""

import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from promethee.avatar_reach import PIXIV_SHA256, load_profile
from promethee.object_models import OBJECT_MODELS


def encoded(value):
    return json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")


class AvatarLiveServer:
    def __init__(self, service, *, avatar, web_root, port, clock=time.monotonic):
        self.service, self.clock = service, clock
        model = Path(avatar).read_bytes()
        if hashlib.sha256(model).hexdigest() != PIXIV_SHA256:
            raise ValueError("Use the pinned pixiv VRM appearance.")
        root = Path(web_root)
        self.routes = {
            "/": ("text/html; charset=utf-8", (root / "index.html").read_bytes()),
            "/style.css": ("text/css", (root / "style.css").read_bytes()),
            "/app.js": ("text/javascript", (root / "app.js").read_bytes()),
            "/app.js.LEGAL.txt": ("text/plain", (root / "app.js.LEGAL.txt").read_bytes()),
            "/avatar.vrm": ("model/gltf-binary", model),
        }
        self.latest = None
        self.published_at = None
        self.bootstrap = None
        self.last_request = None
        self.sequence = 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def send_payload(self, status, content_type, payload):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; connect-src 'self' blob:; "
                    "img-src 'self' blob: data:; worker-src blob:; frame-ancestors 'none'",
                )
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def json_response(self, status, value):
                self.send_payload(status, "application/json", encoded(value))

            def allowed(self, *, mutation=False):
                origin = f"http://127.0.0.1:{self.server.server_port}"
                return self.headers.get("Host") == origin[7:] and (
                    not mutation or self.headers.get("Origin") == origin
                )

            def do_GET(self):
                if not self.allowed():
                    self.json_response(403, {"error": "Unexpected host."})
                    return
                if self.path in owner.routes:
                    self.send_payload(200, *owner.routes[self.path])
                    return
                try:
                    if self.path == "/world.json":
                        self.json_response(200, owner.service.get_world())
                    elif self.path.startswith("/execution/"):
                        self.json_response(
                            200, owner.service.get(self.path.removeprefix("/execution/"))
                        )
                    elif self.path in {"/motion.json", "/state.json"}:
                        if owner.published_at is None or owner.clock() - owner.published_at > 1:
                            self.json_response(503, {"error": "Flux du contrôleur indisponible."})
                            return
                        payload = owner.bootstrap if self.path == "/motion.json" else owner.latest
                        if payload is None:
                            self.json_response(503, {"error": "Chargement du corps…"})
                        else:
                            self.send_payload(200, "application/json", payload)
                    else:
                        self.json_response(404, {"error": "Unknown route."})
                except (ValueError, KeyError) as exc:
                    self.json_response(400, {"error": str(exc)})

            def do_POST(self):
                if not self.allowed(mutation=True):
                    self.json_response(403, {"error": "Same-origin requests only."})
                    return
                if self.path not in {"/action", "/cancel"}:
                    self.json_response(404, {"error": "Unknown route."})
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if (
                        not 0 < size <= 16384
                        or self.headers.get("Content-Type", "").split(";")[0] != "application/json"
                        or self.headers.get("Transfer-Encoding")
                    ):
                        raise ValueError("Use a bounded JSON request.")
                    value = json.loads(self.rfile.read(size))
                    expected = (
                        {"request_id", "expected_revision", "action"}
                        if self.path == "/action"
                        else {"request_id"}
                    )
                    if not isinstance(value, dict) or set(value) != expected:
                        raise ValueError("Unexpected request fields.")
                    if self.path == "/action":
                        item = owner.service.submit(**value)
                    else:
                        item = owner.service.cancel(value["request_id"])
                    owner.last_request = item["request_id"]
                    self.json_response(200, item)
                except (ValueError, KeyError, TypeError, UnicodeError) as exc:
                    self.json_response(400, {"error": str(exc)})

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self):
        return self.server.server_port

    def update(self, controller):
        """Called by the body loop after a tick; publish one immutable coherent snapshot."""
        if not controller.ready or controller.pose is None or controller.skeleton is None:
            return
        hands = set()
        held = controller.observation["avatar"]["holding"]
        if held:
            hands.add(controller.observation["objects"][held]["spatial"]["attachment"]["joint"])
        if controller.object_frames:
            for observation in controller.object_frames:
                for obj in observation["objects"].values():
                    attachment = obj["spatial"]["attachment"]
                    if attachment:
                        hands.add(attachment["joint"])
        if controller.active:
            self.last_request = controller.active["request_id"]
        item = self.service.get(self.last_request) if self.last_request else None
        if self.bootstrap is None:
            self.bootstrap = encoded(
                {
                    "mode": "live",
                    "fps": 20,
                    "frames": [controller.pose],
                    "skeleton": controller.skeleton,
                    "avatar_profile": load_profile(),
                    "object_models": OBJECT_MODELS,
                    "controller_session": controller.handle.session_id,
                    "prepared_appearance": controller.observation.get("appearance") is not None,
                    "initial_appearance": controller.observation.get("appearance"),
                    "initial_objects": controller.observation["objects"],
                    "actions": self.service.supported_actions(),
                }
            )
        self.sequence += 1
        self.latest = encoded(
            {
                "sequence": self.sequence,
                "controller_session": controller.handle.session_id,
                "observation": controller.observation,
                "alignment_hands": sorted(hands),
                "message": controller.message,
                "execution": {
                    key: item[key]
                    for key in ("request_id", "status", "error", "cancel_requested")
                    if key in item
                }
                if item
                else None,
            }
        )
        self.published_at = self.clock()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def run_live_session(service, controller, args):
    server = AvatarLiveServer(service, avatar=args.avatar, web_root=args.web_root, port=args.port)
    print(f"Avatar session: http://127.0.0.1:{server.port}", flush=True)
    try:
        while True:
            started = time.monotonic()
            controller.tick()
            server.update(controller)
            time.sleep(max(0.001, 0.05 - (time.monotonic() - started)))
    finally:
        server.stop()
