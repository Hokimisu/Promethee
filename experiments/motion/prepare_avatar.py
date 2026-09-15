"""Fetch the pinned, explicitly redistributable pixiv VRM sample outside Git."""

import argparse
import hashlib
import json
import struct
import urllib.request
from pathlib import Path

REVISION = "1b4fc0cc7ef39a49d62bb7a66dcfeca8f65316f7"
NAME = "VRM1_Constraint_Twist_Sample.vrm"
SHA256 = "12c2b97e95e700783a6a550dc0eee2d7880aeedccef9ae67bc4c5a2f0f2631a2"
URL = (
    f"https://raw.githubusercontent.com/pixiv/three-vrm/{REVISION}/"
    f"packages/three-vrm/examples/models/{NAME}"
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new directory; existing assets are never overwritten.")
    with urllib.request.urlopen(URL, timeout=60) as response:
        data = response.read(16 * 1024 * 1024 + 1)
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError("Avatar checksum differs from the reviewed asset.")
    magic, version, length, json_length, kind = struct.unpack_from("<4sIIII", data)
    if magic != b"glTF" or version != 2 or length != len(data) or kind != 0x4E4F534A:
        raise ValueError("Invalid VRM/GLB container.")
    document = json.loads(data[20 : 20 + json_length])
    meta = document["extensions"]["VRMC_vrm"]["meta"]
    if (
        meta["authors"] != ["pixiv Inc."]
        or meta["avatarPermission"] != "everyone"
        or meta["allowRedistribution"] is not True
        or meta["modification"] != "allowModificationRedistribution"
        or meta["licenseUrl"] != "https://vrm.dev/licenses/1.0/"
    ):
        raise ValueError("Unexpected avatar license metadata.")
    args.output.mkdir(parents=True)
    (args.output / NAME).write_bytes(data)
    (args.output / "provenance.json").write_text(
        json.dumps(
            {
                "source": URL,
                "revision": REVISION,
                "sha256": SHA256,
                "meta": meta,
                "modified": False,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(args.output / NAME)


if __name__ == "__main__":
    main()
