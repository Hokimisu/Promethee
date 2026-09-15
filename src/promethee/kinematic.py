"""A single kinematic body, advanced by a clock independently of ARDY generation.

Stopping freezes the last played pose. This is not a physics equilibrium claim.
The trajectory gates are provisional until the held-out T07 qualification passes.
"""

import copy
import json
import math
import time
from uuid import uuid4

from promethee.pose import validate_pose
from promethee.world import ActionError

POSTURE_TEXT = {
    "standing": "A person stands still with both arms relaxed down at their sides.",
    "arms_raised": "A person stands still with both arms held straight above the head.",
}


def read_trajectory(path, *, start_pose, target):
    import numpy as np

    with np.load(path, allow_pickle=False) as data:
        positions = data["posed_joints"].copy()
        rotations = data["global_rot_mats"].copy()
        contacts = data["foot_contacts"].copy()
        fps = float(data["fps"])
    if (
        positions.ndim != 3
        or positions.shape[1:] != (27, 3)
        or not 40 <= len(positions) <= 320
        or rotations.shape != (len(positions), 27, 3, 3)
        or contacts.shape != (len(positions), 4)
        or not np.isfinite(contacts).all()
        or fps != 20
    ):
        raise ValueError("Invalid trajectory dimensions or cadence.")
    poses = []
    for points, matrices in zip(positions, rotations, strict=True):
        root = points[0, [0, 2]].tolist()
        if any(abs(value) > 5 for value in root):
            raise ValueError("Generated root leaves the room.")
        poses.append(
            validate_pose(
                {
                    "skeleton": "cskel27",
                    "positions": points.tolist(),
                    "rotations": matrices.tolist(),
                },
                root,
            )
        )
    if start_pose is not None:
        distance = np.linalg.norm(positions[0] - np.asarray(start_pose["positions"]), axis=-1)
        if float(distance.max()) > 0.02:
            raise ValueError("Generated trajectory does not continue the current pose.")
    if np.linalg.norm(positions[-1, 0, [0, 2]] - target) > 0.05:
        raise ValueError("Generated motion misses the target by more than 5 cm.")
    if np.linalg.norm(np.diff(positions[:, 0], axis=0), axis=-1).max() > 0.12:
        raise ValueError("Generated root contains a discontinuity.")
    if np.linalg.norm(np.diff(positions, axis=0), axis=-1).max() > 0.3:
        raise ValueError("Generated joints contain an excessive frame step.")
    feet = positions[:, [25, 26, 21, 22]][..., [0, 2]]
    speed = np.linalg.norm(np.diff(feet, axis=0), axis=-1) * fps
    contact_pairs = (contacts[:-1] > 0.5) & (contacts[1:] > 0.5)
    sliding = speed[contact_pairs]
    if len(sliding) and (sliding.max() > 0.2 or np.quantile(sliding, 0.95) > 0.05):
        raise ValueError("Predicted contact feet slide beyond the calibrated limits.")
    return poses


def posture_reached(pose, name):
    points = pose["positions"]
    wrists = (points[10][1], points[16][1])
    if name == "arms_raised":
        return min(wrists) > points[6][1] + 0.15
    return max(wrists) < points[4][1] and points[6][1] > points[0][1] + 0.5


class KinematicController:
    def __init__(self, service, worker, *, clock=time.monotonic, seed=0):
        world = service.runtime.require_session()
        if world["objects"] or world["avatar"]["holding"] or world["avatar"]["seated_on"]:
            raise ActionError("This controller has not qualified object interactions yet.")
        self.service, self.worker, self.clock = service, worker, clock
        self.world_id = world["world_id"]
        self.handle = service.acquire_controller(
            source="kinematic", supported_actions=["move", "posture"]
        )
        self.observation = {key: copy.deepcopy(world[key]) for key in ("avatar", "objects", "pose")}
        self.active = None
        self.sequence = 0
        self.job_id = None
        self.trajectory = None
        self.frame = 0
        self.ready = False
        self.seed = seed
        self.next_heartbeat = 0.0
        self.next_checkpoint = 0.0
        self.started_at = clock()
        self.job_started = self.started_at
        self.closed = False
        self.message = "Chargement du contrôleur cinématique."

    @property
    def pose(self):
        return self.observation["pose"]

    def _observe_pose(self, pose):
        self.observation["pose"] = copy.deepcopy(pose)
        root = pose["positions"][0]
        self.observation["avatar"]["position"] = [root[0], root[2]]

    def _feedback(self, status, error=None):
        self.sequence += 1
        if not self.handle.feedback(
            self.active["request_id"],
            self.sequence,
            status,
            observation=self.observation,
            error=error,
        ):
            raise RuntimeError("Controller feedback lost ownership or its execution.")
        if status != "running":
            self.message = {
                "completed": "Mouvement terminé.",
                "cancelled": "Mouvement arrêté.",
                "failed": "Mouvement non réalisé.",
            }[status]
            self.active = None
            self.trajectory = None
            self.job_id = None

    def _submit_motion(self, target, text, frames):
        self.job_id = uuid4().hex
        job = {
            "job_id": self.job_id,
            "target": target,
            "text": text,
            "seed": self.seed,
            "frames": frames,
            "start_pose": self.pose,
            "posture": (
                self.active["envelope"]["action"]["args"].get("name") if self.active else None
            ),
        }
        with (self.worker.output / f"{self.job_id}-request.json").open(
            "x", encoding="utf-8"
        ) as stream:
            json.dump(
                {
                    "world_id": self.world_id,
                    "request_id": self.active["request_id"] if self.active else None,
                    "controller_session": self.handle.session_id,
                    "purpose": "body-initialization" if self.active is None else "body-action",
                    "source": "kinematic",
                    "job": job,
                },
                stream,
                allow_nan=False,
            )
        self.worker.submit(job)
        self.seed = (self.seed + 1) % (2**31)
        self.job_started = self.clock()

    def _result(self, item):
        if item["job_id"] != self.job_id:
            return  # Cancelled generation: retained locally, never played later.
        try:
            if item["type"] == "error":
                raise ValueError(item["error"])
            expected_file = f"{self.job_id}-processed.npz"
            if item.get("file") != expected_file:
                raise ValueError("Unexpected trajectory filename.")
            target = self.observation["avatar"]["position"]
            if self.active and self.active["envelope"]["action"]["kind"] == "move":
                target = self.active["envelope"]["action"]["args"]["position"]
            poses = read_trajectory(
                self.worker.output / expected_file, start_pose=self.pose, target=target
            )
        except (ValueError, OSError, KeyError) as exc:
            if not self.active:
                raise RuntimeError(f"Cannot initialize the body: {exc}") from exc
            self._feedback("failed", str(exc))
            return
        if not self.ready:
            # Instantiation of the virtual body; no action or hidden activity is created.
            self._observe_pose(poses[0])
            if not self.handle.reconcile(self.observation, stopped=True):
                raise RuntimeError("Body initialization lost controller ownership.")
            self.ready = True
            self.job_id = None
            self.message = "Corps cinématique prêt."
        else:
            self.trajectory = poses
            self.frame = 0
            self.play_started = self.clock()
            self.message = "Mouvement en cours."

    def tick(self):
        now = self.clock()
        if self.closed:
            raise RuntimeError("Controller is closed.")
        if now >= self.next_heartbeat:
            if not self.handle.heartbeat():
                raise RuntimeError("Controller lease lost; playback stopped.")
            self.next_heartbeat = now + 1
        cancellation = self.handle.claim_cancellation()
        if cancellation:
            if not self.active or cancellation["request_id"] != self.active["request_id"]:
                raise RuntimeError("Cancellation does not match the active body.")
            self._feedback("cancelled")
        while item := self.worker.poll():
            if item["type"] == "crashed":
                raise RuntimeError(item["error"])
            if item["type"] == "ready":
                (self.worker.output / "conventions.json").write_text(
                    json.dumps(item["skeleton"]), encoding="utf-8"
                )
                if self.pose is not None:
                    # This body is virtual: restore its last persisted checkpoint explicitly.
                    if not self.handle.reconcile(self.observation, stopped=True):
                        raise RuntimeError("Checkpoint restoration lost ownership.")
                    self.ready = True
                    self.message = "Corps cinématique restauré au dernier point enregistré."
                else:
                    self._submit_motion(
                        self.observation["avatar"]["position"], POSTURE_TEXT["standing"], 40
                    )
            elif item["type"] in {"generated", "error"}:
                self._result(item)
        now = self.clock()
        if not self.ready and now - self.started_at > 180:
            raise TimeoutError("Motion initialization exceeded 180 seconds.")
        if self.worker.pending is not None and now - self.job_started > 60:
            raise TimeoutError("Motion generation exceeded 60 seconds.")
        if self.trajectory is not None:
            self.frame = min(int((now - self.play_started) * 20), len(self.trajectory) - 1)
            self._observe_pose(self.trajectory[self.frame])
            if self.frame == len(self.trajectory) - 1:
                action = self.active["envelope"]["action"]
                if action["kind"] == "posture" and not posture_reached(
                    self.pose, action["args"]["name"]
                ):
                    self._feedback(
                        "failed", "The observed final pose does not satisfy the requested posture."
                    )
                else:
                    self._feedback("completed")
            elif now >= self.next_checkpoint:
                self._feedback("running")
                self.next_checkpoint = now + 0.25
        if self.ready and self.active is None and self.worker.pending is None:
            self.active = self.handle.claim_next()
            if self.active:
                self.sequence = 0
                self._feedback("running")
                action = self.active["envelope"]["action"]
                target = self.observation["avatar"]["position"]
                text = POSTURE_TEXT.get(action["args"].get("name"))
                if action["kind"] == "move":
                    target = action["args"]["position"]
                    text = "A person walks to the target and stops."
                if math.dist(target, self.observation["avatar"]["position"]) > 2:
                    self._feedback(
                        "failed",
                        "Movement above 2 metres is not qualified; choose a closer target.",
                    )
                else:
                    self.message = "Préparation du mouvement."
                    self._submit_motion(target, text, 120)

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self.handle.release()
            finally:
                self.worker.close()
