"""Test an explicit whole-body vertical floor projection on the actual Core mesh.

No root XZ or joint rotations are changed. This is kinematic geometry correction,
not an equilibrium solver. Original ARDY files remain intact.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from ardy.skeleton.definitions import CoreSkeleton27
from ardy.viz.core_skin import CoreSkin


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("motion", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    with np.load(args.motion, allow_pickle=False) as data:
        values = {key: data[key].copy() for key in data.files}
    skin = CoreSkin(CoreSkeleton27())
    positions, rotations = values["posed_joints"], values["global_rot_mats"]
    offsets = []
    with torch.inference_mode():
        for points, matrices in zip(positions, rotations, strict=True):
            mesh = skin.skin(
                torch.from_numpy(matrices[None]), torch.from_numpy(points[None]), rot_is_global=True
            )
            offsets.append(max(0.0, -float(mesh[..., 1].min())))
    lift = np.asarray(offsets, dtype=positions.dtype)
    values["posed_joints"][:, :, 1] += lift[:, None]
    values["root_positions"][:, 1] += lift
    np.savez(args.output / "grounded.npz", **values)
    result = {
        "source": str(args.motion),
        "correction": "whole-body positive-Y mesh-floor projection",
        "max_lift_m": float(lift.max()),
        "first_lift_m": float(lift[0]),
        "max_lift_step_m": float(np.abs(np.diff(lift)).max()),
        "root_xz_unchanged": True,
        "rotations_unchanged": True,
    }
    (args.output / "grounding.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
