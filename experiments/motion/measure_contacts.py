"""Measure actual Core skin/floor penetration and contact-conditioned foot motion.

Run with the pinned ARDY environment. Predicted foot contacts are not collision sensors.
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
    parser.add_argument("motions", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    skeleton = CoreSkeleton27()
    skin = CoreSkin(skeleton)
    indices = skin.lbs_indices.numpy()
    weights = skin.lbs_weights.numpy()
    foot_vertices = (np.isin(indices, [21, 22, 25, 26]) * weights).sum(axis=-1) > 0.5
    results = []
    for path in args.motions:
        with np.load(path, allow_pickle=False) as data:
            joints = data["posed_joints"].copy()
            rotations = data["global_rot_mats"].copy()
            contacts = data["foot_contacts"].copy()
            fps = float(data["fps"])
        minima = []
        sole_frames = []
        with torch.inference_mode():
            for points, matrices in zip(joints, rotations, strict=True):
                vertices = skin.skin(
                    torch.from_numpy(matrices[None]),
                    torch.from_numpy(points[None]),
                    rot_is_global=True,
                )
                minima.append(float(vertices[..., 1].min()))
                sole_frames.append(vertices[0].numpy()[foot_vertices])
        feet = joints[:, [25, 26, 21, 22]][..., [0, 2]]
        speeds = np.linalg.norm(np.diff(feet, axis=0), axis=-1) * fps
        both_contact = (contacts[:-1] > 0.5) & (contacts[1:] > 0.5)
        sliding = speeds[both_contact]
        penetration = np.maximum(0, -np.asarray(minima))
        sole = np.asarray(sole_frames)
        geometric_contact = (sole[:-1, :, 1] <= 0.005) & (sole[1:, :, 1] <= 0.005)
        sole_speed = np.linalg.norm(np.diff(sole[..., [0, 2]], axis=0), axis=-1) * fps
        geometric_sliding = sole_speed[geometric_contact]
        results.append(
            {
                "motion": str(path),
                "frames": len(joints),
                "fps": fps,
                "mesh_floor_penetration_max_m": float(penetration.max()),
                "mesh_floor_penetration_p95_m": float(np.quantile(penetration, 0.95)),
                "frames_mesh_below_floor_1cm": int((penetration > 0.01).sum()),
                "contact_pairs": int(both_contact.sum()),
                "geometric_vertex_contact_pairs": int(geometric_contact.sum()),
                "geometric_contact_speed_max_m_s": float(geometric_sliding.max())
                if len(geometric_sliding)
                else None,
                "geometric_contact_speed_p95_m_s": float(np.quantile(geometric_sliding, 0.95))
                if len(geometric_sliding)
                else None,
                "geometric_contact_definition": (
                    "Same foot-weighted vertex within 5 mm of floor in consecutive frames; "
                    "foot weights >0.5."
                ),
                "contact_foot_speed_max_m_s": float(sliding.max()) if len(sliding) else None,
                "contact_foot_speed_p95_m_s": float(np.quantile(sliding, 0.95))
                if len(sliding)
                else None,
                "note": "Core skin; predicted contacts >0.5 at consecutive frames; no physics.",
            }
        )
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(results, stream, indent=2)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
