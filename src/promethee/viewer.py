"""Optional Viser reader: it has no execution service and never writes to the world."""

import argparse
import math
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote

from promethee.rendering import load_skeleton, read_snapshot, rest_pose, world_to_xyz


def load_motion(path, np):
    """Only the numeric, world-coordinate Core exports from T02 are supported."""
    with np.load(path, allow_pickle=False) as data:
        positions = data["posed_joints"].copy()
        fps = float(data["fps"])
    if positions.ndim != 3 or positions.shape[1:] != (27, 3):
        raise ValueError("Expected motion positions with shape [T,27,3].")
    if not 1 <= len(positions) <= 72000 or not np.isfinite(positions).all():
        raise ValueError("Invalid or oversized motion.")
    if not math.isfinite(fps) or not 1 <= fps <= 120:
        raise ValueError("Invalid playback rate.")
    return positions, fps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--skeleton", type=Path, required=True)
    parser.add_argument("--motion", type=Path)
    parser.add_argument(
        "--heading",
        type=float,
        default=0.0,
        help="Diagnostic neutral-pose heading in radians; no world mutation.",
    )
    parser.add_argument("--port", type=int, default=2335)
    args = parser.parse_args()
    try:
        import numpy as np
        import viser
    except ImportError:
        parser.exit(2, "Install the optional viewer: uv sync --extra viewer\n")
    try:
        skeleton = load_skeleton(args.skeleton)
        state = read_snapshot(args.database)
        neutral = rest_pose(skeleton, state["avatar"]["position"], args.heading)
        motion, fps = load_motion(args.motion, np) if args.motion else (None, 20)
    except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
        parser.exit(2, f"Cannot open viewer: {exc}\n")

    server = viser.ViserServer(host="127.0.0.1", port=args.port, label="Promethee")
    server.scene.set_up_direction("+y")
    server.scene.add_grid(
        "/floor", width=10, height=10, plane="xz", cell_size=1, section_size=1, infinite_grid=False
    )
    server.scene.add_frame("/origin", axes_length=1, axes_radius=0.008)
    for name, pos in (("X +1 m", (1, 0, 0)), ("Y logique +1 m", (0, 0, 1))):
        server.scene.add_label(f"/axes/{name}", name, position=pos)

    @server.on_client_connect
    def connect(client):
        client.camera.position = (5, 4, 6)
        client.camera.look_at = (0, 0.8, 0)

    status = server.gui.add_markdown("")
    parents = np.asarray(skeleton["parents"])[1:]
    children = np.arange(1, 27)
    points = np.asarray(neutral)
    body = server.scene.add_line_segments(
        "/avatar",
        points=points[np.stack([parents, children], axis=1)],
        colors=(80, 155, 225),
        line_width=5,
    )
    markers = {}
    playing = (
        server.gui.add_checkbox("Lire le mouvement", initial_value=False)
        if motion is not None
        else None
    )
    frame = (
        server.gui.add_slider("Pose", min=0, max=max(1, len(motion) - 1), step=1, initial_value=0)
        if motion is not None
        else None
    )
    if motion is not None:
        server.gui.add_markdown(
            "Lecture d'un enregistrement de test ; "
            "elle ne modifie pas le corps enregistré dans le monde."
        )
    else:
        server.gui.add_markdown(
            "Squelette neutre de diagnostic ; aucune posture du corps n'est encore observée."
        )

    def update_world(snapshot):
        status.content = (
            f"Monde `{snapshot['world_id']}` · révision {snapshot['revision']} · "
            f"{snapshot['data_origin']} · corps {snapshot['body']['status']}"
        )
        objects = snapshot["objects"]
        for key in markers.keys() - objects.keys():
            for handle in markers.pop(key):
                handle.remove()
        for key, obj in objects.items():
            pos = world_to_xyz(obj["position"])
            if key not in markers:
                node = "/objects/" + quote(key, safe="")
                markers[key] = (
                    server.scene.add_frame(node, axes_length=0.15, axes_radius=0.005),
                    server.scene.add_label(
                        node + "/label", f"{key} · {obj['asset']} · asset absent"
                    ),
                )
            markers[key][0].position = pos
            # Label is a child: its offset is local to the object marker.
            markers[key][1].position = (0, 0.2, 0)

    update_world(state)
    next_read = 0.0
    read_failed = False
    started = time.monotonic()
    previous_playing = False
    while True:
        tick = time.monotonic()
        if tick >= next_read:
            try:
                current = read_snapshot(args.database)
                if current != state or read_failed:
                    update_world(current)
                    state = current
                read_failed = False
            except (ValueError, OSError, sqlite3.Error) as exc:
                status.content = (
                    f"Lecture indisponible : {type(exc).__name__}. Dernier état conservé."
                )
                read_failed = True
            next_read = tick + 0.25
        if motion is None:
            points = np.asarray(rest_pose(skeleton, state["avatar"]["position"], args.heading))
        else:
            if playing.value:
                if not previous_playing:
                    started = tick - int(frame.value) / fps
                frame.value = int((tick - started) * fps) % len(motion)
            previous_playing = playing.value
            points = motion[min(int(frame.value), len(motion) - 1)]
        body.points = points[np.stack([parents, children], axis=1)]
        time.sleep(max(0.001, 1 / fps - (time.monotonic() - tick)))


if __name__ == "__main__":
    main()
