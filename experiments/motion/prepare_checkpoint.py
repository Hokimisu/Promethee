"""Download the pinned ARDY Core checkpoint into a new local directory."""

import argparse
import shutil
from pathlib import Path

from huggingface_hub import snapshot_download

NAME = "ARDY-Core-RP-20FPS-Horizon40"
REVISION = "abe6c43beb28c867c950acb824b9c4ef3d63fb76"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    if args.directory.exists():
        parser.error("Choose a new checkpoint directory.")
    cached = snapshot_download(f"nvidia/{NAME}", revision=REVISION, token=False)
    args.directory.mkdir(parents=True, exist_ok=False)
    shutil.copytree(cached, args.directory / NAME)
    print(args.directory.resolve())


if __name__ == "__main__":
    main()
