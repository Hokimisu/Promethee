"""Read-only VRM retargeting trial: fixed local files, no world writes or action API."""

import argparse
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from promethee.avatar_reach import PIXIV_SHA256, load_profile
from promethee.object_models import OBJECT_MODELS
from promethee.pose import validate_pose
from promethee.rendering import load_skeleton
from promethee.world import validate_observation


def motion_document(path, skeleton, objects=None):
    import numpy as np

    with np.load(path, allow_pickle=False) as data:
        positions = data["posed_joints"]
        rotations = data["global_rot_mats"]
        fps = float(data["fps"])
    if positions.ndim != 3 or positions.shape[1:] != (27, 3):
        raise ValueError("Expected Core27 positions.")
    if rotations.shape != (len(positions), 27, 3, 3) or not 1 <= len(positions) <= 1200:
        raise ValueError("Expected 1-1200 articulated Core27 poses.")
    if fps != 20:
        raise ValueError("This retargeting trial supports the qualified 20 FPS model.")
    frames = [
        validate_pose(
            {"skeleton": "cskel27", "positions": points.tolist(), "rotations": rots.tolist()},
            [float(points[0, 0]), float(points[0, 2])],
        )
        for points, rots in zip(positions, rotations, strict=True)
    ]
    document = {
        "fps": fps,
        "frames": frames,
        "skeleton": load_skeleton(skeleton),
        "avatar_profile": load_profile(),
    }
    if objects is not None:
        if Path(objects).stat().st_size > 16 * 1024 * 1024:
            raise ValueError("Object replay exceeds 16 MiB.")
        observations = json.loads(Path(objects).read_text(encoding="utf-8"))
        if not isinstance(observations, list) or len(observations) != len(frames):
            raise ValueError(
                "Object replay must contain one complete observation per motion frame."
            )
        values = []
        for observation, frame in zip(observations, frames, strict=True):
            observed = validate_observation(observation)
            if observed["pose"] != frame:
                raise ValueError("Object replay and motion poses disagree.")
            for obj in observed["objects"].values():
                if "spatial" not in obj or obj["asset"] not in OBJECT_MODELS:
                    raise ValueError(
                        "Object replay requires a spatial pose and a known visual model."
                    )
            values.append(observed["objects"])
        document.update(objects=values, object_models=OBJECT_MODELS)
    return document


def create_server(*, web_root, avatar, motion, skeleton, port=2343, objects=None):
    model = Path(avatar).read_bytes()
    if hashlib.sha256(model).hexdigest() != PIXIV_SHA256:
        raise ValueError("Use the pinned pixiv sample with its verified license and fingerprint.")
    root = Path(web_root)
    routes = {
        "/": ("text/html; charset=utf-8", (root / "index.html").read_bytes()),
        "/style.css": ("text/css", (root / "style.css").read_bytes()),
        "/app.js": ("text/javascript", (root / "app.js").read_bytes()),
        "/app.js.LEGAL.txt": ("text/plain", (root / "app.js.LEGAL.txt").read_bytes()),
        "/avatar.vrm": ("model/gltf-binary", model),
        "/motion.json": (
            "application/json",
            json.dumps(motion_document(motion, skeleton, objects), allow_nan=False).encode(),
        ),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            host = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != host:
                self.send_error(403)
                return
            if self.path not in routes:
                self.send_error(404)
                return
            content_type, payload = routes[self.path]
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; connect-src 'self' blob:; "
                "img-src 'self' blob: data:; worker-src blob:; "
                "frame-ancestors 'none'",
            )
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("web-root", "avatar", "motion", "skeleton"):
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--port", type=int, default=2343)
    parser.add_argument(
        "--objects", type=Path, help="Optional complete observations matching every frame."
    )
    args = parser.parse_args()
    with create_server(**vars(args)) as server:
        print(f"Avatar replay: http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
