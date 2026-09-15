"""Check frozen T02 root criteria; does not certify gestures or physical contacts."""

import argparse
import json
import math
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("measurements", type=Path)
    args = parser.parse_args()
    criteria = json.loads(Path(__file__).with_name("criteria.json").read_text())
    records = json.loads(args.measurements.read_text())
    if len(records) != 3 or len({row["seed"] for row in records}) != 3:
        parser.error("Expected three distinct cases.")
    checks = {
        "raw_start_error_m": "max_start_error_m",
        "target_error_m": "max_target_error_m",
        "root_max_frame_step_m": "max_root_frame_step_m",
    }
    failures = []
    for row in records:
        if row["frames"] != 120 or row["fps"] != 20 or row["all_finite"] is not True:
            failures.append({"seed": row["seed"], "error": "Invalid duration or non-finite poses"})
        for metric, limit in checks.items():
            value = row[metric]
            if not math.isfinite(value) or not 0 <= value <= criteria[limit]:
                failures.append({"seed": row["seed"], "metric": metric, "value": value})
    print(json.dumps({"passed": not failures, "failures": failures}, indent=2))
    raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
