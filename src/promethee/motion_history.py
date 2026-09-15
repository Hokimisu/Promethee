"""Bounded observed Core history and explicitly separate, committed future poses."""

import copy
import hashlib
import math
from collections import deque


class ExecutedHistory:
    def __init__(self):
        self.samples = deque(maxlen=160)
        self.bucket = None

    def record(self, pose, now):
        bucket = math.floor(now * 20 + 1e-6)
        if self.bucket is not None and bucket not in (self.bucket, self.bucket + 1):
            # A skipped observation is not evidence that intermediate poses played.
            self.samples.clear()
        if bucket == self.bucket:
            self.samples.pop()
        self.samples.append(copy.deepcopy(pose))
        self.bucket = bucket

    def context(self, committed=()):
        observed = list(self.samples)
        if observed and committed and observed[-1] == committed[0]:
            observed.pop()
        poses = (observed + list(committed))[-160:]
        count = len(poses) // 4 * 4
        return copy.deepcopy(poses[-count:]) if count else [], min(len(committed), count)


def write_history(output, job_id, poses, committed_frames):
    """Keep numeric history out of the bounded worker JSON protocol."""
    if not poses:
        return None
    import numpy as np

    path = output / f"{job_id}-history.npz"
    with path.open("xb") as stream:
        np.savez(
            stream,
            posed_joints=np.asarray([p["positions"] for p in poses], dtype=np.float32),
            global_rot_mats=np.asarray([p["rotations"] for p in poses], dtype=np.float32),
            fps=np.asarray(20),
        )
    return {
        "file": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "frames": len(poses),
        "executed_frames": len(poses) - committed_frames,
        "committed_frames": committed_frames,
    }
