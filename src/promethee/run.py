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

    if args.prepare_avatar and args.avatar is None:
        raise ValueError("Prepared appearance requires --avatar.")

    database = args.data_dir / "world.sqlite3"
    runtime = Runtime(
        database,
        data_origin="session",
        session_kind="interactive" if not database.exists() else None,
    )
    runtime.require_session()
    service = ExecutionService(runtime)
    worker = start_ardy_process(
        python=args.ardy_python,
        checkpoint_root=args.checkpoint_root,
        output=args.data_dir / "motions",
        wsl=args.wsl,
        encoder_url=args.encoder_url,
    )
    appearance = None
    try:
        from promethee.avatar_reach import PixivArmReach

        if args.prepare_avatar:
            from promethee.appearance_process import AppearancePreparation

            appearance = AppearancePreparation(
                avatar=args.avatar,
                script=args.web_root.parent / "measure-feet.mjs",
                output=args.data_dir / "appearance",
            )

        controller = KinematicController(
            service,
            worker,
            seed=args.seed,
            object_interactions=args.object_interactions,
            arm_reach_check=PixivArmReach().check if args.object_interactions else None,
            appearance_preparation=appearance,
        )
    except Exception:
        worker.close()
        if appearance is not None:
            appearance.close()
        raise
    server = None
    try:
        if args.avatar is not None:
            from promethee.avatar_live import run_live_session

            run_live_session(service, controller, args)
            return
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

        if args.object_interactions:
            with server.gui.add_folder("Objets"):
                name = server.gui.add_text("Nom de l’objet", initial_value="")
                model = server.gui.add_dropdown("Modèle", options=("Doudou", "Balle"))
                location = server.gui.add_vector3(
                    "Position XYZ (m)",
                    initial_value=(0, 1, 0.5),
                    min=(-5, 0, -5),
                    max=(5, 5, 5),
                    step=0.05,
                    hint="Y est la hauteur. Les objets libres restent fixes, sans gravité.",
                )
                create = server.gui.add_button("Créer l’objet")
                take = server.gui.add_button("Prendre l’objet")
                place = server.gui.add_button("Déposer l’objet tenu")

            @create.on_click
            def create_clicked(_):
                submit(
                    {
                        "kind": "spawn",
                        "args": {
                            "object_id": name.value,
                            "asset": "plush" if model.value == "Doudou" else "ball",
                            "position": list(location.value),
                        },
                    }
                )

            @take.on_click
            def take_clicked(_):
                submit({"kind": "take", "args": {"object_id": name.value}})

            @place.on_click
            def place_clicked(_):
                submit({"kind": "place", "args": {"position": list(location.value)}})

        body = None
        object_nodes = {}
        edges = None
        next_status = 0.0
        while True:
            tick = time.monotonic()
            controller.tick()
            if controller.pose is not None and controller.skeleton is not None:
                if edges is None:
                    edges = np.stack(
                        [np.asarray(controller.skeleton["parents"])[1:], np.arange(1, 27)], axis=1
                    )
                points = np.asarray(controller.pose["positions"])[edges]
                if body is None:
                    body = server.scene.add_line_segments(
                        "/avatar", points=points, colors=(80, 155, 225), line_width=5
                    )
                else:
                    body.points = points
            if args.object_interactions:
                from viser.transforms import SO3

                from promethee.object_models import OBJECT_MODELS, part_mesh

                observed_objects = controller.observation["objects"]
                for object_id in set(object_nodes) - set(observed_objects):
                    parent, children = object_nodes.pop(object_id)
                    for node in children:
                        node.remove()
                    parent.remove()
                for object_id, obj in observed_objects.items():
                    if object_id not in object_nodes:
                        path = f"/objects/{object_id}"
                        parent = server.scene.add_frame(path, show_axes=False)
                        children = []
                        for index, part in enumerate(OBJECT_MODELS[obj["asset"]]):
                            vertices, faces = part_mesh(part)
                            color = tuple(int(part["color"][i : i + 2], 16) for i in (1, 3, 5))
                            children.append(
                                server.scene.add_mesh_simple(
                                    f"{path}/part-{index}",
                                    vertices=vertices,
                                    faces=faces,
                                    color=color,
                                )
                            )
                        object_nodes[object_id] = (parent, children)
                    parent = object_nodes[object_id][0]
                    parent.position = tuple(obj["spatial"]["position"])
                    parent.wxyz = SO3.from_matrix(np.asarray(obj["spatial"]["rotation"])).wxyz
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
    parser.add_argument(
        "--avatar", type=Path, help="Use the pinned pixiv VRM for the live session."
    )
    parser.add_argument("--web-root", type=Path, default=Path("web/avatar/dist"))
    parser.add_argument(
        "--prepare-avatar",
        action="store_true",
        help="Experimentally prepare and persist VRM support poses before playback.",
    )
    parser.add_argument(
        "--object-interactions",
        action="store_true",
        help="Enable experimental kinematic spatial spawn/take/place.",
    )


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
