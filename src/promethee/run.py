"""Manual session UI with one kinematic controller and independent pose playback."""

import argparse
import time
from pathlib import Path
from uuid import uuid4

from promethee.execution import ExecutionService
from promethee.kinematic import KinematicController
from promethee.motion_process import start_ardy_process
from promethee.runtime import Runtime


def run_session(args):
    import numpy as np
    import viser

    runtime = Runtime(args.data_dir / "world.sqlite3", data_origin="session")
    runtime.require_session()
    service = ExecutionService(runtime)
    worker = start_ardy_process(
        python=args.ardy_python,
        checkpoint_root=args.checkpoint_root,
        output=args.data_dir / "motions",
        wsl=args.wsl,
        encoder_url=args.encoder_url,
    )
    try:
        controller = KinematicController(service, worker, seed=args.seed)
    except Exception:
        worker.close()
        raise
    server = None
    try:
        server = viser.ViserServer(host="127.0.0.1", port=args.port, label="Promethee")
        server.scene.set_up_direction("+y")
        server.scene.add_grid(
            "/floor",
            width=10,
            height=10,
            plane="xz",
            cell_size=1,
            section_size=1,
            infinite_grid=False,
        )

        @server.on_client_connect
        def connect(client):
            client.camera.position = (3, 2.5, 4)
            client.camera.look_at = (0, 0.9, 0)

        status = server.gui.add_markdown("Chargement du corps cinématique.")
        x = server.gui.add_number("Cible X (m)", initial_value=0.0, min=-5, max=5, step=0.1)
        z = server.gui.add_number("Cible Y au sol (m)", initial_value=0.0, min=-5, max=5, step=0.1)
        move = server.gui.add_button("Se déplacer")
        posture = server.gui.add_dropdown("Posture", options=("Debout", "Bras levés"))
        change = server.gui.add_button("Changer de posture")
        stop = server.gui.add_button("Arrêter le mouvement")
        result = server.gui.add_markdown("")
        request = [None]

        def submit(action):
            state = service.get_world()
            request_id = "manual-" + uuid4().hex
            item = service.submit(request_id, state["revision"], action)
            if item["status"] != "rejected":
                request[0] = request_id
            result.content = f"{request_id} : {item['status']}" + (
                f" · {item['error']['message']}" if "error" in item else ""
            )

        @move.on_click
        def move_clicked(_):
            submit({"kind": "move", "args": {"position": [float(x.value), float(z.value)]}})

        @change.on_click
        def posture_clicked(_):
            submit(
                {
                    "kind": "posture",
                    "args": {"name": "standing" if posture.value == "Debout" else "arms_raised"},
                }
            )

        @stop.on_click
        def stop_clicked(_):
            if request[0]:
                item = service.cancel(request[0])
                result.content = f"{request[0]} : {item['status']} · arrêt demandé"

        body = None
        edges = None
        next_status = 0.0
        while True:
            tick = time.monotonic()
            controller.tick()
            if controller.pose is not None:
                if edges is None:
                    from promethee.rendering import load_skeleton

                    skeleton = load_skeleton(worker.output / "conventions.json")
                    edges = np.stack(
                        [np.asarray(skeleton["parents"])[1:], np.arange(1, 27)], axis=1
                    )
                points = np.asarray(controller.pose["positions"])[edges]
                if body is None:
                    body = server.scene.add_line_segments(
                        "/avatar", points=points, colors=(80, 155, 225), line_width=5
                    )
                else:
                    body.points = points
            if tick >= next_status:
                status.content = controller.message
                if request[0]:
                    item = service.get(request[0])
                    result.content = f"{request[0]} : {item['status']}" + (
                        f" · {item['error']['message']}" if "error" in item else ""
                    )
                next_status = tick + 0.25
            time.sleep(max(0.001, 0.05 - (time.monotonic() - tick)))
    finally:
        controller.close()
        if server is not None:
            server.stop()


def configure(parser):
    parser.add_argument("--ardy-python", required=True)
    parser.add_argument("--checkpoint-root", required=True)
    parser.add_argument("--wsl")
    parser.add_argument("--encoder-url", default="http://127.0.0.1:9550")
    parser.add_argument("--port", type=int, default=2335)
    parser.add_argument("--seed", type=int, default=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    configure(parser)
    args = parser.parse_args()
    try:
        run_session(args)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    main()
