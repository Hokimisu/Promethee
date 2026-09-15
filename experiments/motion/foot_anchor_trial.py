"""Diagnostic two-bone IK on predicted support intervals; not a runtime backend."""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
from ardy.skeleton.definitions import CoreSkeleton27
from ardy.viz.core_skin import CoreSkin

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from promethee.ardy_contacts import measure_skin_contacts, stabilize_contacts  # noqa: E402
from promethee.ardy_geometry import continue_from_pose, ground_motion  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--from-raw", action="store_true")
    parser.add_argument("--geometry-support", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "trial-source.py").write_text(Path(__file__).read_text())
    (args.output / "purpose.json").write_text(
        json.dumps(
            {
                "purpose": "developer geometry qualification; exclude from agent memory",
                "request": str(args.request),
                "from_raw": args.from_raw,
                "geometry_support": args.geometry_support,
            },
            indent=2,
        )
    )
    for name in ("ardy_contacts.py", "ardy_geometry.py"):
        source = Path(__file__).resolve().parents[2] / "src" / "promethee" / name
        (args.output / name).write_text(source.read_text())
    job = json.loads(args.request.read_text())["job"]
    path = args.request.with_name(
        job["job_id"] + ("-raw.npz" if args.from_raw else "-processed.npz")
    )
    with np.load(path, allow_pickle=False) as data:
        values = {key: data[key].copy() for key in data.files}
    skeleton = CoreSkeleton27()
    skin = CoreSkin(skeleton)
    if args.from_raw:
        continue_from_pose(values, job["start_pose"], skeleton)
    predicted = values["foot_contacts"].copy()
    if args.geometry_support:
        grounded = {key: value.copy() for key, value in values.items()}
        ground_motion(grounded, skin)
        indices, weights = skin.lbs_indices.numpy(), skin.lbs_weights.numpy()
        masks = [
            (np.isin(indices, bones) * weights).sum(axis=-1) > 0.5 for bones in ([25, 26], [21, 22])
        ]
        geometry = np.zeros_like(predicted, dtype=bool)
        with torch.inference_mode():
            for i, (p, r) in enumerate(
                zip(grounded["posed_joints"], grounded["global_rot_mats"], strict=True)
            ):
                vertices = skin.skin(
                    torch.from_numpy(r[None]), torch.from_numpy(p[None]), rot_is_global=True
                )[0].numpy()
                for foot, mask in enumerate(masks):
                    geometry[i, foot * 2 : foot * 2 + 2] = vertices[mask, 1].min() <= 0.005
        values["geometry_support"] = geometry
        values["foot_contacts"] = (predicted > 0.5) | geometry
    residual = stabilize_contacts(values, skeleton)
    values["foot_contacts"] = predicted
    grounding = ground_motion(values, skin)
    np.savez(args.output / "anchored.npz", **values)
    joints, contact = values["posed_joints"], values["foot_contacts"] > 0.5
    speeds = (
        np.linalg.norm(np.diff(joints[:, [25, 26, 21, 22]][:, :, [0, 2]], axis=0), axis=-1) * 20
    )
    active = speeds[contact[1:] & contact[:-1]]
    report = {
        "source": str(path),
        "geometry_support": args.geometry_support,
        "skin_contacts": measure_skin_contacts(values, skin),
        "grounding": grounding,
        "max_unreachable_residual_m": residual,
        "first_pose_error_m": float(
            np.linalg.norm(joints[0] - job["start_pose"]["positions"], axis=-1).max()
        ),
        "target_error_m": float(np.linalg.norm(joints[-1, 0, [0, 2]] - job["target"])),
        "max_joint_step_m": float(np.linalg.norm(np.diff(joints, axis=0), axis=-1).max()),
        "max_predicted_contact_speed_m_s": float(active.max()),
        "p95_predicted_contact_speed_m_s": float(np.percentile(active, 95)),
    }
    (args.output / "summary.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
