"""Offline signed mesh-floor projection; never modifies the runtime or source clips."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import torch
from ardy.skeleton.definitions import CoreSkeleton27
from ardy.viz.core_skin import CoreSkin

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from promethee.ardy_contacts import measure_skin_contacts, validate_sole_contacts  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = sorted(path for root in args.inputs for path in root.glob("*-processed.npz"))
    if not paths:
        parser.error("No processed recordings found.")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "trial-source.py").write_bytes(Path(__file__).read_bytes())
    contact_source = Path(__file__).resolve().parents[2] / "src/promethee/ardy_contacts.py"
    (args.output / "ardy_contacts.py").write_bytes(contact_source.read_bytes())
    config = {
        "purpose": "developer calibration, excluded from agent memory",
        "method": "signed whole-body translation to the minimum Core skin height each frame",
        "max_absolute_shift_m": 0.05,
        "max_shift_step_m": 0.015,
        "inputs": [
            {"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths
        ],
    }
    (args.output / "config.json").write_text(json.dumps(config, indent=2))
    skin = CoreSkin(CoreSkeleton27())
    reports = []
    for index, path in enumerate(paths):
        with np.load(path, allow_pickle=False) as data:
            values = {key: data[key].copy() for key in data.files}
        before = measure_skin_contacts(values, skin)
        heights = []
        with torch.inference_mode():
            for points, rotations in zip(
                values["posed_joints"], values["global_rot_mats"], strict=True
            ):
                mesh = skin.skin(
                    torch.from_numpy(rotations[None]),
                    torch.from_numpy(points[None]),
                    rot_is_global=True,
                )
                heights.append(float(mesh[..., 1].min()))
        shifts = -np.asarray(heights, dtype=values["posed_joints"].dtype)
        values["posed_joints"][:, :, 1] += shifts[:, None]
        values["root_positions"][:, 1] += shifts
        after = measure_skin_contacts(values, skin)
        failures = []
        if np.abs(shifts).max() > config["max_absolute_shift_m"]:
            failures.append("absolute shift exceeds 5 cm")
        step = float(np.abs(np.diff(shifts)).max())
        if step > config["max_shift_step_m"]:
            failures.append("shift step exceeds 15 mm/frame")
        try:
            validate_sole_contacts(after)
        except ValueError as exc:
            failures.append(str(exc))
        destination = args.output / f"clip-{index:02d}.npz"
        np.savez(destination, **values)
        report = {
            "source": str(path),
            "corrected": destination.name,
            "before": before,
            "after": after,
            "maximum_absolute_shift_m": float(np.abs(shifts).max()),
            "first_pose_shift_m": float(abs(shifts[0])),
            "maximum_shift_step_m": step,
            "max_joint_step_m": float(
                np.linalg.norm(np.diff(values["posed_joints"], axis=0), axis=-1).max()
            ),
            "failures": failures,
        }
        reports.append(report)
        (args.output / "report.json").write_text(json.dumps(reports, indent=2))
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
