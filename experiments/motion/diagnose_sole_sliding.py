"""Locate geometric sliding peaks on the actual Core skin without changing poses."""

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
    with np.load(args.motion, allow_pickle=False) as data:
        joints = data["posed_joints"].copy()
        rotations = data["global_rot_mats"].copy()
        contacts = data["foot_contacts"].copy()
        fps = float(data["fps"])
    skin = CoreSkin(CoreSkeleton27())
    indices, weights = skin.lbs_indices.numpy(), skin.lbs_weights.numpy()
    left = (np.isin(indices, [25, 26]) * weights).sum(axis=-1)
    right = (np.isin(indices, [21, 22]) * weights).sum(axis=-1)
    selected = np.flatnonzero(left + right > 0.5)
    frames = []
    with torch.inference_mode():
        for p, r in zip(joints, rotations, strict=True):
            vertices = skin.skin(
                torch.from_numpy(r[None]), torch.from_numpy(p[None]), rot_is_global=True
            )
            frames.append(vertices[0].numpy()[selected])
    frames = np.asarray(frames)
    near = (frames[:-1, :, 1] <= 0.005) & (frames[1:, :, 1] <= 0.005)
    speed = np.linalg.norm(np.diff(frames[..., [0, 2]], axis=0), axis=-1) * fps
    pairs = np.argwhere(near)
    top = sorted(pairs.tolist(), key=lambda pair: speed[tuple(pair)], reverse=True)[:10]
    peaks = []
    for frame, vertex in top:
        vertex_id = selected[vertex]
        is_left = left[vertex_id] > right[vertex_id]
        slots = [0, 1] if is_left else [2, 3]
        ankle = 25 if is_left else 21
        delta = rotations[frame + 1, ankle] @ rotations[frame, ankle].T
        peaks.append(
            {
                "frame_pair": [frame, frame + 1],
                "vertex_id": int(vertex_id),
                "foot": "left" if is_left else "right",
                "speed_m_s": float(speed[frame, vertex]),
                "heights_m": frames[frame : frame + 2, vertex, 1].tolist(),
                "predicted_heel_toe": contacts[frame : frame + 2, slots].tolist(),
                "ankle_rotation_step_degrees": float(
                    np.degrees(np.arccos(np.clip((np.trace(delta) - 1) / 2, -1, 1)))
                ),
            }
        )
    report = {
        "motion": str(args.motion),
        "purpose": "developer diagnosis; exclude from memory",
        "peaks": peaks,
    }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
