"""Compare walking support projection on archived Core output, outside the runtime."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from ardy.skeleton.definitions import CoreSkeleton27
from ardy.viz.core_skin import CoreSkin

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from promethee.ardy_contacts import (  # noqa: E402
    measure_skin_contacts,
    project_support,
    stabilize_contacts,
    validate_sole_contacts,
)
from promethee.ardy_geometry import continue_from_pose  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    job = json.loads(args.request.read_text())["job"]
    if job["posture"] is not None or job["start_pose"] is None:
        parser.error("Use a walking request with an observed starting pose.")
    source = args.request.with_name(job["job_id"] + "-raw.npz")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "trial-source.py").write_bytes(Path(__file__).read_bytes())
    (args.output / "request.json").write_bytes(args.request.read_bytes())
    for name in ("ardy_contacts.py", "ardy_geometry.py"):
        path = Path(__file__).resolve().parents[2] / "src/promethee" / name
        (args.output / name).write_bytes(path.read_bytes())
    report = {
        "purpose": "developer calibration; exclude from agent memory",
        "source": str(source),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    with np.load(source, allow_pickle=False) as data:
        values = {key: data[key].copy() for key in data.files}
    skeleton = CoreSkeleton27()
    skin = CoreSkin(skeleton)
    try:
        continue_from_pose(values, job["start_pose"], skeleton)
        report["anchor_residual_m"] = stabilize_contacts(values, skeleton)
        report["projection"] = project_support(values, skin)
        report["contacts"] = measure_skin_contacts(values, skin)
        validate_sole_contacts(report["contacts"], continuous_support=True)
        report["start_error_m"] = float(
            np.linalg.norm(
                values["posed_joints"][0] - job["start_pose"]["positions"], axis=-1
            ).max()
        )
        report["max_joint_step_m"] = float(
            np.linalg.norm(np.diff(values["posed_joints"], axis=0), axis=-1).max()
        )
        report["target_error_m"] = float(
            np.linalg.norm(values["posed_joints"][-1, 0, [0, 2]] - job["target"])
        )
        if (
            report["start_error_m"] > 0.02
            or report["max_joint_step_m"] > 0.3
            or report["target_error_m"] > 0.05
        ):
            raise ValueError("Target or joint continuity gate failed.")
        np.savez(args.output / "motion.npz", **values)
    except ValueError as exc:
        report["error"] = str(exc)
    (args.output / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
