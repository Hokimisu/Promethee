"""Arm reach of the pinned pixiv appearance, matching its normalized VRM rig.

The profile does not establish finger contact, skin collision or joint limits.
The browser independently checks its rest geometry and scale against the profile.
"""

import json
from importlib.resources import files

from promethee.avatar_rotation import normalized_core_rotation

PIXIV_SHA256 = "12c2b97e95e700783a6a550dc0eee2d7880aeedccef9ae67bc4c5a2f0f2631a2"


def load_profile():
    profile = json.loads(files("promethee").joinpath("pixiv_arm_profile.json").read_text("utf-8"))
    if profile["version"] != 1 or profile["asset_sha256"] != PIXIV_SHA256:
        raise ValueError("Unknown avatar reach profile.")
    return profile


class PixivArmReach:
    def __init__(self):
        self.profile = load_profile()

    def check(self, pose, skeleton, hand, *, root_y_offset=0.0):
        """Check an observed wrist after a known, bounded appearance-root translation.

        The Core pose and world-space hand target remain unchanged. The caller
        must supply the offset actually used by its qualified appearance adapter.
        This does not compute or authorize a floor correction on its own.
        """
        import numpy as np

        from promethee.pose import validate_pose

        if hand not in {"RightHand", "LeftHand"}:
            raise ValueError("Unknown avatar hand.")
        if (
            type(root_y_offset) not in {int, float}
            or not np.isfinite(root_y_offset)
            or abs(root_y_offset) > 0.05
        ):
            raise ValueError("Avatar root height offset must be finite and within 5 cm.")
        height = -min(point[1] for point in skeleton["neutral_joints"])
        if abs(height - self.profile["core_hip_height"]) > 1e-6:
            raise ValueError("Core rest height differs from the qualified avatar scale.")
        validate_pose(pose, [pose["positions"][0][0], pose["positions"][0][2]])
        bones, scale = self.profile["bones"], self.profile["scale"]
        side = "right" if hand == "RightHand" else "left"
        chain = ["hips", "spine", "chest", "upperChest", side + "Shoulder", side + "UpperArm"]
        names = skeleton["joint_names"]
        position = np.asarray(pose["positions"][0], dtype=float).copy()
        position[1] += root_y_offset
        rotations = [normalized_core_rotation(rows) for rows in pose["rotations"]]
        for parent, child in zip(chain[:-1], chain[1:], strict=True):
            offset = (
                np.array(bones[child]["rest_position"]) - bones[parent]["rest_position"]
            ) * scale
            position += rotations[names.index(bones[parent]["source"])] @ offset
        upper = (
            np.linalg.norm(
                np.array(bones[side + "LowerArm"]["rest_position"])
                - bones[side + "UpperArm"]["rest_position"]
            )
            * scale
        )
        lower = (
            np.linalg.norm(
                np.array(bones[side + "Hand"]["rest_position"])
                - bones[side + "LowerArm"]["rest_position"]
            )
            * scale
        )
        distance = np.linalg.norm(np.array(pose["positions"][names.index(hand)]) - position)
        if not abs(upper - lower) + 1e-5 < distance < upper + lower - 1e-5:
            raise ValueError(
                f"Wrist target outside pixiv avatar arm reach ({distance:.6f} m; "
                f"maximum {upper + lower:.6f} m)."
            )
        return {"distance_m": float(distance), "maximum_m": float(upper + lower)}
