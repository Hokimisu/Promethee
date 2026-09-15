"""Compare ARDY sampling on archived requests, outside the world."""

import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path

import numpy as np
from omegaconf import OmegaConf

from promethee.motion_process import MotionProcess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=10)
    parser.add_argument("--guidance", type=float, choices=(1.0, 2.0, 3.0), default=2.0)
    parser.add_argument("--ardy-python", required=True)
    parser.add_argument("--checkpoint-root", required=True)
    args = parser.parse_args()
    config = Path(args.checkpoint_root) / "ARDY-Core-RP-20FPS-Horizon40/config.yaml"
    base_steps = int(OmegaConf.load(config).num_base_steps)
    if not 1 <= args.steps <= base_steps:
        parser.error(f"This checkpoint supports 1 to {base_steps} sampling steps.")
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(config, args.output / "model-config.yaml")
    source = Path(__file__).resolve().parents[2] / "src/promethee"
    worker_source = (source / "ardy_worker.py").read_text()
    needle = "                    frames,\n                    10,\n"
    if worker_source.count(needle) != 1 or worker_source.count("cfg_weight=(2.0, 2.0)") != 1:
        raise ValueError("Worker sampling call changed; review the trial before running.")
    worker_path = args.output / "ardy_worker.py"
    worker_path.write_text(
        worker_source.replace(
            needle, f"                    frames,\n                    {args.steps},\n"
        ).replace("cfg_weight=(2.0, 2.0)", f"cfg_weight=({args.guidance}, {args.guidance})")
    )
    for name in ("ardy_geometry.py", "ardy_contacts.py"):
        shutil.copyfile(source / name, args.output / name)
    shutil.copyfile(__file__, args.output / "trial-source.py")
    shutil.copyfile(
        Path(__file__).with_name("runtime-criteria.json"), args.output / "criteria.json"
    )
    output = args.output / "motions"
    worker = MotionProcess(
        [
            args.ardy_python,
            "-u",
            str(worker_path),
            "--checkpoint-root",
            args.checkpoint_root,
            "--output",
            str(output),
        ],
        output,
    )
    results = []

    def wait_for(kind, timeout=180):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            item = worker.poll()
            if item and item["type"] in {kind, "error", "crashed"}:
                return item
            time.sleep(0.02)
        raise TimeoutError("Denoising trial worker timed out.")

    try:
        if wait_for("ready")["type"] != "ready":
            raise RuntimeError("Worker did not become ready.")
        for request in args.request:
            content = request.read_bytes()
            job = json.loads(content)["job"]
            (output / f"{job['job_id']}-request.json").write_bytes(content)
            worker.submit(job)
            result = wait_for("generated")
            result.update(request=str(request), request_sha256=hashlib.sha256(content).hexdigest())
            motion = output / f"{job['job_id']}-processed.npz"
            if motion.exists():
                with np.load(motion, allow_pickle=False) as data:
                    joints = data["posed_joints"]
                    result["max_joint_step_m"] = float(
                        np.linalg.norm(np.diff(joints, axis=0), axis=-1).max()
                    )
                    result["pelvis_tilt_max_deg"] = float(
                        np.rad2deg(
                            np.arccos(np.clip(data["global_rot_mats"][:, 0, 1, 1], -1, 1))
                        ).max()
                    )
            results.append(result)
            print(json.dumps(result), flush=True)
            if "CUDA error" in result.get("error", "") or result["type"] == "crashed":
                break
    finally:
        worker.close()
        (args.output / "report.json").write_text(
            json.dumps(
                {
                    "purpose": "developer calibration; exclude from agent memory",
                    "steps": args.steps,
                    "guidance": args.guidance,
                    "results": results,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
