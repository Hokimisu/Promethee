"""Export a validated replay and its archived ARDY foot flags for VRM calibration."""

import argparse
import json
from pathlib import Path

import numpy as np

from promethee.avatar_viewer import motion_document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--motion", type=Path, required=True)
    parser.add_argument("--skeleton", type=Path, required=True)
    parser.add_argument("--objects", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    document = motion_document(args.motion, args.skeleton, args.objects)
    with np.load(args.motion, allow_pickle=False) as data:
        if "foot_contacts" in data:
            contacts = data["foot_contacts"]
            if contacts.dtype != np.bool_ or contacts.shape != (len(document["frames"]), 4):
                raise ValueError("Expected four archived boolean contact flags per frame.")
            document["foot_contacts"] = contacts.tolist()
    document["purpose"] = "VRM foot calibration; exclude from personal memory"
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, allow_nan=False)
    print(args.output)


if __name__ == "__main__":
    main()
