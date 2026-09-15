"""Render actual Core mesh trajectories to local MP4 evidence, without a browser.

Software orthographic rendering uses the upstream skin and recorded transforms.
Red faces intersect the floor. No smoothing, retiming or pose correction is applied.
"""

import argparse
import json
import math
import subprocess
from pathlib import Path

import numpy as np
import torch
from ardy.skeleton.definitions import CoreSkeleton27
from ardy.viz.core_skin import CoreSkin
from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("motion", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--yaw", type=float, default=35.0)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    with np.load(args.motion, allow_pickle=False) as data:
        positions = data["posed_joints"].copy()
        rotations = data["global_rot_mats"].copy()
        fps = float(data["fps"])
    skin = CoreSkin(CoreSkeleton27())
    faces = skin.faces.numpy()
    center = positions[:, 0].mean(axis=0)
    center[1] = 1.15
    yaw, pitch = math.radians(args.yaw), math.radians(12.0)
    right = np.asarray([math.cos(yaw), 0, -math.sin(yaw)])
    up = np.asarray(
        [-math.sin(yaw) * math.sin(pitch), math.cos(pitch), -math.cos(yaw) * math.sin(pitch)]
    )
    depth = np.cross(right, up)
    scale = 185.0

    def project(points):
        relative = points - center
        return np.stack([320 + relative @ right * scale, 310 - relative @ up * scale], axis=-1)

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-n",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        "640x640",
        "-r",
        str(fps),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        str(args.output / "motion.mp4"),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with torch.inference_mode():
            for frame, (points, matrices) in enumerate(zip(positions, rotations, strict=True)):
                vertices = skin.skin(
                    torch.from_numpy(matrices[None]),
                    torch.from_numpy(points[None]),
                    rot_is_global=True,
                )[0].numpy()
                screen = project(vertices)
                triangles = vertices[faces]
                normals = np.cross(
                    triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
                )
                normals /= np.maximum(np.linalg.norm(normals, axis=-1, keepdims=True), 1e-10)
                light = np.clip(0.55 + 0.45 * np.abs(normals @ np.asarray([0.3, 0.8, 0.52])), 0, 1)
                order = np.argsort(triangles.mean(axis=1) @ depth)
                image = Image.new("RGB", (640, 640), (246, 246, 242))
                draw = ImageDraw.Draw(image)
                for value in range(-6, 7):
                    for line in (
                        np.asarray([[value, 0, -6], [value, 0, 6]]),
                        np.asarray([[-6, 0, value], [6, 0, value]]),
                    ):
                        draw.line(
                            [tuple(point) for point in project(line)], fill=(200, 202, 197), width=1
                        )
                for index in order:
                    color = (
                        np.asarray([75, 145, 200])
                        if triangles[index, :, 1].min() >= -0.001
                        else np.asarray([235, 65, 55])
                    )
                    draw.polygon(
                        [tuple(point) for point in screen[faces[index]]],
                        fill=tuple((color * light[index]).astype(int)),
                    )
                draw.rectangle((0, 0, 640, 45), fill=(246, 246, 242))
                draw.text(
                    (12, 8),
                    f"Core mesh | {frame}/{len(positions) - 1} | {frame / fps:.2f} s | {fps:g} FPS",
                    fill=(30, 35, 40),
                )
                draw.text(
                    (12, 25), "Red = mesh below floor; kinematic playback", fill=(130, 40, 35)
                )
                if frame in {0, len(positions) // 2, len(positions) - 1}:
                    image.save(args.output / f"frame-{frame:03d}.png")
                process.stdin.write(image.tobytes())
        process.stdin.close()
        error = process.stderr.read().decode()
        if process.wait() != 0:
            raise RuntimeError(error)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stderr.close()
    (args.output / "render.json").write_text(
        json.dumps(
            {
                "motion": str(args.motion),
                "frames": len(positions),
                "fps": fps,
                "yaw": args.yaw,
                "pitch": 12,
                "projection": "orthographic",
                "pixels_per_metre": scale,
                "pose_changes": False,
            },
            indent=2,
        )
    )
    print(args.output / "motion.mp4")


if __name__ == "__main__":
    main()
