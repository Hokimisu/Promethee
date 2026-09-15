"""Measure geometric reaching on a real Core pose; no grasp or world action is claimed."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np

from promethee.arm_reach import ARMS, reach_arm
from promethee.rendering import load_skeleton


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--motion", type=Path, required=True)
    parser.add_argument("--skeleton", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--hand-rotation",
        type=float,
        nargs=9,
        help="Optional row-major hand rotation in the unturned world frame.",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, args.output / "qualification-source.py")
    shutil.copyfile(
        Path(__file__).resolve().parents[2] / "src/promethee/arm_reach.py",
        args.output / "arm-reach-source.py",
    )
    skeleton = load_skeleton(args.skeleton)
    with np.load(args.motion, allow_pickle=False) as data:
        points = data["posed_joints"][0].astype(float)
        rotations = data["global_rot_mats"][0].astype(float)
        contacts = data["foot_contacts"][0]
    results = []
    for heading in (0, np.pi / 2):
        c, s = np.cos(heading), np.sin(heading)
        rotation = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
        translated = points @ rotation.T + ([0, 0, 0] if heading == 0 else [1, 0, -1])
        turned = rotation @ rotations
        for side, names in ARMS.items():
            shoulder, elbow, wrist, _ = [skeleton["joint_names"].index(n) for n in names]
            for offset in ([0, -0.25, 0.25], [0.1, -0.15, 0.4], [-0.1, 0.1, 0.35]):
                target = translated[shoulder] + rotation @ np.array(offset)
                pose = {
                    "skeleton": "cskel27",
                    "positions": translated.tolist(),
                    "rotations": turned.tolist(),
                }
                hand_target = (
                    None
                    if args.hand_rotation is None
                    else rotation @ np.array(args.hand_rotation).reshape(3, 3)
                )
                values = reach_arm(
                    pose, skeleton, target.tolist(), side=side, hand_rotation=hand_target
                )
                name = f"reach-{len(results):02}"
                positions = values["posed_joints"]
                matrices = values["global_rot_mats"]
                local_hands = np.swapaxes(matrices[:, elbow], -1, -2) @ matrices[:, wrist]
                hand_steps = np.swapaxes(matrices[:-1, wrist], -1, -2) @ matrices[1:, wrist]
                changed = set([elbow, wrist])
                changed.update(i for i, parent in enumerate(skeleton["parents"]) if parent == wrist)
                static = [i for i in range(27) if i not in changed]
                report = {
                    "case": name,
                    "side": side,
                    "heading": heading,
                    "target": target.tolist(),
                    "source": "geometric-arm-ik",
                    "grasp_validated": False,
                    "hand_mode": "follow-forearm" if hand_target is None else "target-rotation",
                    "hand_target": None if hand_target is None else hand_target.tolist(),
                    "hand_target_matrix_error": None
                    if hand_target is None
                    else float(np.max(np.abs(matrices[-1, wrist] - hand_target))),
                    "local_hand_matrix_change": float(np.max(np.abs(local_hands - local_hands[0]))),
                    "max_hand_rotation_step_deg": float(
                        np.rad2deg(
                            np.arccos(
                                np.clip((np.trace(hand_steps, axis1=-2, axis2=-1) - 1) / 2, -1, 1)
                            )
                        ).max()
                    ),
                    "upper_arm_m": values["upper_arm_m"],
                    "forearm_m": values["forearm_m"],
                    "wrist_error_m": float(np.linalg.norm(positions[-1, wrist] - target)),
                    "unchanged_joints_error_m": float(
                        np.max(np.abs(positions[:, static] - translated[static]))
                    ),
                    "max_joint_step_m": float(
                        np.linalg.norm(np.diff(positions, axis=0), axis=-1).max()
                    ),
                    "wrist_speed_max_m_s": float(
                        np.linalg.norm(np.diff(positions[:, wrist], axis=0), axis=-1).max() * 20
                    ),
                }
                assert report["wrist_error_m"] < 1e-5
                assert report["unchanged_joints_error_m"] < 1e-5
                if hand_target is None:
                    assert report["local_hand_matrix_change"] < 1e-6
                else:
                    assert report["hand_target_matrix_error"] < 1e-6
                np.savez_compressed(
                    args.output / f"{name}.npz",
                    posed_joints=positions.astype(np.float32),
                    global_rot_mats=values["global_rot_mats"].astype(np.float32),
                    root_positions=positions[:, 0].astype(np.float32),
                    fps=20.0,
                    foot_contacts=np.repeat(contacts[None], len(positions), axis=0),
                )
                results.append(report)
    report = {
        "purpose": "developer geometry qualification, not personal memory",
        "source_motion": str(args.motion.resolve()),
        "source_sha256": hashlib.sha256(args.motion.read_bytes()).hexdigest(),
        "skeleton_sha256": hashlib.sha256(args.skeleton.read_bytes()).hexdigest(),
        "cases": results,
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
