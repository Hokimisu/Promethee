"""Compare CPU arm preflight with actual settled VRM object replays, outside a world."""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from promethee.avatar_reach import PixivArmReach
from promethee.avatar_viewer import motion_document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--avatar", type=Path, required=True)
    parser.add_argument("--replays", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    for source in (
        Path(__file__),
        root / "src/promethee/avatar_reach.py",
        root / "src/promethee/avatar_rotation.py",
        root / "src/promethee/pixiv_arm_profile.json",
        root / "web/avatar/measure-feet.mjs",
        root / "web/avatar/retarget.js",
        root / "web/avatar/align-hand.js",
        root / "web/avatar/foot-geometry.js",
        root / "web/avatar/package-lock.json",
    ):
        shutil.copyfile(source, args.output / source.name)
    reach = PixivArmReach()
    results = []
    try:
        for index, replay in enumerate(args.replays):
            data = motion_document(
                replay / "motion.npz", replay / "conventions.json", replay / "objects.json"
            )
            document = args.output / f"replay-{index}.json"
            document.write_text(json.dumps(data), encoding="utf-8")
            measurement = args.output / f"measurement-{index}.json"
            subprocess.run(
                [
                    "node",
                    str(root / "web/avatar/measure-feet.mjs"),
                    str(args.avatar.resolve()),
                    str(document.resolve()),
                    str(measurement.resolve()),
                    "--settle",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=90,
            )
            measured = json.loads(measurement.read_text(encoding="utf-8"))
            item = {"replay": str(replay), "status": "failed"}
            results.append(item)
            if measured["error"] is not None:
                item["error"] = measured["error"]
                continue
            assert measured["motion_sha256"] == hashlib.sha256(document.read_bytes()).hexdigest()
            assert measured["avatar_sha256"] == reach.profile["asset_sha256"]
            assert len(measured["root_offsets_m"]) == len(data["frames"])
            hands = measured["measured_attached_hands"]
            assert hands and measured["maximum_attached_hand_error_m"] < 1e-5
            distances = []
            for frame, offset in zip(data["frames"], measured["root_offsets_m"], strict=True):
                for hand in hands:
                    distances.append(
                        reach.check(frame, data["skeleton"], hand, root_y_offset=offset)[
                            "distance_m"
                        ]
                    )
            item.update(
                status="passed",
                frames=len(data["frames"]),
                hands=hands,
                minimum_distance_m=min(distances),
                maximum_distance_m=max(distances),
                maximum_vrm_hand_error_m=measured["maximum_attached_hand_error_m"],
                minimum_root_offset_m=min(measured["root_offsets_m"]),
                maximum_root_offset_m=max(measured["root_offsets_m"]),
            )
            print(json.dumps(item), flush=True)
    finally:
        (args.output / "report.json").write_text(
            json.dumps(
                {
                    "purpose": "developer qualification; exclude from personal memory",
                    "results": results,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
