"""A single kinematic body, advanced by a clock independently of ARDY generation.

Stopping freezes the last played pose. This is not a physics equilibrium claim.
The trajectory gates are provisional until the held-out T07 qualification passes.
"""

import copy
import json
import math
import time
from uuid import uuid4

from promethee.motion_history import ExecutedHistory, write_history
from promethee.pose import validate_pose
from promethee.world import ActionError

POSTURE_TEXT = {
    "standing": "A person stands still with both arms relaxed down at their sides.",
    "arms_raised": "A person stands still with both arms held straight above the head.",
}
UNSUPPORTED_PHASE = "ValueError: Walking has a predicted phase without foot support."
RETRYABLE_MOTION_ERRORS = {
    UNSUPPORTED_PHASE: "un appui prédit manquant",
    "ValueError: Foot mesh slides beyond the geometric contact limits (": "un glissement des pieds",
}
MAX_MOTION_ATTEMPTS = 3
DEFAULT_TARGET_TOLERANCE_M = 0.05
FREE_WALK_TARGET_TOLERANCE_M = 1.0


def read_trajectory(path, *, start_pose, target, target_tolerance_m=DEFAULT_TARGET_TOLERANCE_M):
    import numpy as np

    if (
        type(target_tolerance_m) not in (int, float)
        or not math.isfinite(target_tolerance_m)
        or target_tolerance_m <= 0
    ):
        raise ValueError("Target tolerance must be finite and positive.")
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
    if (
        target is not None
        and np.linalg.norm(positions[-1, 0, [0, 2]] - target) > target_tolerance_m
    ):
        raise ValueError(
            f"Generated motion misses the target by more than {target_tolerance_m:g} m."
        )
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


def read_contact_flags(path):
    import numpy as np

    with np.load(path, allow_pickle=False) as data:
        flags = data["foot_contacts"]
        if flags.dtype != np.bool_ or flags.ndim != 2 or flags.shape[1] != 4:
            raise ValueError("Appearance preparation requires archived boolean contact flags.")
        return flags.tolist()


class KinematicController:
    def __init__(
        self,
        service,
        worker,
        *,
        clock=time.monotonic,
        seed=0,
        object_interactions=False,
        arm_reach_check=None,
        appearance_preparation=None,
        continuous_motion=False,
    ):
        world = service.runtime.require_session()
        if world.get("appearance") is not None and appearance_preparation is None:
            raise ActionError("Restore this session with prepared appearance mode enabled.")
        if world["avatar"]["seated_on"] or (
            not object_interactions and (world["objects"] or world["avatar"]["holding"])
        ):
            raise ActionError("This controller has not qualified object interactions yet.")
        if object_interactions and world["objects"]:
            from promethee.object_actions import check_clearance

            check_clearance(world)
        self.service, self.worker, self.clock = service, worker, clock
        self.world_id = world["world_id"]
        self.handle = service.acquire_controller(
            source="kinematic",
            supported_actions=["move", "posture"]
            + (["spawn", "take", "place"] if object_interactions else []),
        )
        self.observation = {key: copy.deepcopy(world[key]) for key in ("avatar", "objects", "pose")}
        if appearance_preparation is not None:
            self.observation["appearance"] = copy.deepcopy(world.get("appearance"))
        self.appearance_preparation = appearance_preparation
        self.appearance_job = None
        self.preparation = None
        self.appearance_frames = None
        self.continuous_motion = continuous_motion
        self.history = ExecutedHistory()
        self.motion_remaining = None
        self.stream_id = None
        self.segment_remaining = 0
        self.future_segment = None
        self.stream_expected = None
        self.active = None
        self.sequence = 0
        self.job_id = None
        self.motion_attempt = 0
        self.motion_origin = None
        self.motion_spec = None
        self.motion_context = None
        self.trajectory = None
        self.object_frames = None
        self.object_expected = None
        self.skeleton = None
        self.arm_reach_check = arm_reach_check
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
        held = self.observation["avatar"]["holding"]
        if held:
            from promethee.spatial import follow_attachment

            self.observation["objects"][held] = follow_attachment(
                self.observation["objects"][held], pose
            )

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
            self._stream_event(status, error=error)
            if self.appearance_preparation is not None:
                self.appearance_preparation.cancel()
            self.appearance_job = self.preparation = self.appearance_frames = None
            self.message = {
                "completed": "Mouvement terminé.",
                "cancelled": "Mouvement arrêté.",
                "failed": "Mouvement non réalisé.",
            }[status]
            self.active = None
            self.trajectory = None
            self.job_id = None
            self.motion_attempt = 0
            self.motion_origin = self.motion_spec = None
            self.motion_context = None
            self.object_frames = None
            self.object_expected = None
            self.future_segment = None
            self.motion_remaining = None
            self.stream_id = None
            self.segment_remaining = 0
            self.stream_expected = None

    def _stream_event(self, event, **details):
        if not self.continuous_motion:
            return
        record = {
            "event": event,
            "seconds": self.clock() - self.started_at,
            "world_id": self.world_id,
            "controller_session": self.handle.session_id,
            "request_id": self.active["request_id"] if self.active else None,
            **details,
        }
        with (self.worker.output / "stream-events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, allow_nan=False) + "\n")

    def _prepare_appearance(
        self,
        poses,
        object_frames=None,
        contacts=None,
        *,
        origin=None,
        remaining=None,
        stationary_support=False,
    ):
        from promethee.avatar_reach import load_profile
        from promethee.spatial import follow_attachment

        origin = self.observation if origin is None else origin
        document = {
            "fps": 20,
            "frames": poses,
            "skeleton": self.skeleton,
            "avatar_profile": load_profile(),
        }
        if object_frames is not None:
            document["objects"] = [frame["objects"] for frame in object_frames]
        else:
            document["objects"] = []
            for pose in poses:
                objects = copy.deepcopy(origin["objects"])
                held = origin["avatar"]["holding"]
                if held:
                    objects[held] = follow_attachment(objects[held], pose)
                document["objects"].append(objects)
        if contacts is not None:
            document["foot_contacts"] = contacts
        if origin.get("appearance") is not None:
            document.update(initial_pose=origin["pose"], initial_appearance=origin["appearance"])
        if remaining is not None:
            document["observed_origin"] = True
        if stationary_support:
            document["stationary_support"] = True
        self.appearance_job = self.appearance_preparation.submit(
            document, mode="--plant" if contacts is not None else "--settle"
        )
        self.preparation = {
            "poses": poses,
            "objects": object_frames,
            "expected": copy.deepcopy(origin),
            "remaining": remaining,
            "started": self.clock(),
        }
        if self.trajectory is None:
            self.message = "Préparation de la pose visible."

    def _appearance_result(self, item):
        if item["job_id"] != self.appearance_job:
            return  # Includes a cancelled job whose result arrived after its acknowledgement.
        from promethee.appearance_checkpoint import appearance_checkpoint

        try:
            if item["type"] != "prepared":
                raise ValueError(item.get("error", "Appearance preparation was cancelled."))
            pending = self.preparation
            if pending["remaining"] is None and self.observation != pending["expected"]:
                raise ValueError("The observed body changed during appearance preparation.")
            poses = pending["poses"]
            artifact = item["appearance"]
            if len(artifact["frames"]) != len(poses):
                raise ValueError("Prepared appearance frame count differs from the body.")
            appearances = [appearance_checkpoint(artifact, i, pose) for i, pose in enumerate(poses)]
            if pending["remaining"] is not None:
                initial = pending["expected"]["appearance"]

                def weights(value):
                    return value.get(
                        "alignment_weights",
                        {
                            hand: float(hand in value["aligned_hands"])
                            for hand in ("RightHand", "LeftHand")
                        },
                    )

                if appearances[0]["frame"] != initial["frame"] or weights(
                    appearances[0]
                ) != weights(initial):
                    raise ValueError(
                        "Prepared continuous origin differs from the observed appearance."
                    )
                # Its visual contents were checked above. Preserve the original checkpoint
                # provenance rather than claiming that the origin was generated again.
                appearances[0] = copy.deepcopy(initial)
                self._stream_event(
                    "appearance_ready",
                    job_id=item["job_id"],
                    elapsed_seconds=self.clock() - pending["started"],
                )
                self.appearance_job = self.preparation = None
                self.job_id = None
                self._accept_segment(poses, appearances, pending["expected"], pending["remaining"])
                return
            if not self.ready:
                self._observe_pose(poses[0])
                self.observation["appearance"] = appearances[0]
                if not self.handle.reconcile(self.observation, stopped=True):
                    raise RuntimeError("Appearance initialization lost controller ownership.")
                self.ready = True
                self.job_id = None
                self.message = "Corps cinématique prêt."
            else:
                self.trajectory = poses
                self.appearance_frames = appearances
                self.object_frames = pending["objects"]
                self.object_expected = copy.deepcopy(self.observation)
                self.frame = 0
                self.play_started = self.clock()
                self.message = "Mouvement en cours."
            self.appearance_job = self.preparation = None
        except (ValueError, KeyError, TypeError) as exc:
            if not self.active:
                raise RuntimeError(f"Cannot initialize the visible body: {exc}") from exc
            self._feedback("failed", str(exc))

    def _accept_segment(self, poses, appearances, origin, remaining):
        segment = {
            "poses": poses,
            "appearances": appearances,
            "origin": origin,
            "remaining": remaining,
        }
        if self.trajectory is None:
            self._start_segment(segment)
        else:
            if self.future_segment is not None:
                raise ValueError("A future motion segment is already committed.")
            self.future_segment = segment

    def _start_segment(self, segment):
        if self.observation != segment["origin"]:
            raise ValueError("The body or its objects differ from the committed segment boundary.")
        self.trajectory = segment["poses"]
        self.appearance_frames = segment["appearances"]
        self.segment_remaining = segment["remaining"]
        self.frame = 0
        self.play_started = self.clock()
        self.stream_expected = copy.deepcopy(self.observation)
        self.message = "Mouvement en cours."
        self._stream_event(
            "segment_started", poses=len(self.trajectory), remaining=self.segment_remaining
        )
        if self.segment_remaining:
            target, text, _ = self.motion_spec
            self.motion_attempt = 0
            self._submit_motion(
                target,
                text,
                self.segment_remaining,
                origin=self._segment_boundary(),
                context=self.history.context(self.trajectory[1:]),
            )

    def _segment_boundary(self):
        from promethee.spatial import follow_attachment

        # This is an immutable future boundary, not an observed state.
        origin = copy.deepcopy(self.observation)
        origin["pose"] = copy.deepcopy(self.trajectory[-1])
        root = origin["pose"]["positions"][0]
        origin["avatar"]["position"] = [root[0], root[2]]
        held = origin["avatar"]["holding"]
        if held:
            origin["objects"][held] = follow_attachment(origin["objects"][held], origin["pose"])
        if self.appearance_frames is not None:
            origin["appearance"] = copy.deepcopy(self.appearance_frames[-1])
        return origin

    def _submit_motion(self, target, text, frames, *, origin=None, context=None):
        self.motion_attempt += 1
        if self.motion_attempt == 1:
            self.motion_origin = copy.deepcopy(self.observation if origin is None else origin)
            self.motion_started_at = self.clock()
        self.motion_spec = (copy.deepcopy(target), text, frames)
        self.job_id = uuid4().hex
        streaming = self.continuous_motion and self.ready and self.active is not None
        self.motion_remaining = frames if streaming else None
        job = {
            "job_id": self.job_id,
            "target": target,
            "text": text,
            "seed": self.seed,
            "frames": 40 if streaming else frames,
            "start_pose": self.motion_origin["pose"],
            "posture": (
                self.active["envelope"]["action"]["args"].get("name") if self.active else None
            ),
        }
        if streaming:
            if self.stream_id is None:
                self.stream_id = self.job_id
            if context is None:
                if self.motion_attempt > 1:
                    context = self.motion_context
                else:
                    self.history.record(self.pose, self.clock())
                    context = self.history.context()
            self.motion_context = copy.deepcopy(context)
            poses, committed = context
            job.update(
                future_frames=frames,
                stream_id=self.stream_id,
                history=write_history(self.worker.output, self.job_id, poses, committed),
            )
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
                    "generation_attempt": self.motion_attempt,
                    "job": job,
                },
                stream,
                allow_nan=False,
            )
        self.worker.submit(job)
        if streaming:
            self._stream_event(
                "generation_requested", job_id=self.job_id, remaining=frames, history=job["history"]
            )
        self.seed = (self.seed + 1) % (2**31)
        self.job_started = self.clock()

    def _retry_motion_quality(self, item):
        reason = next(
            (
                label
                for prefix, label in RETRYABLE_MOTION_ERRORS.items()
                if item.get("error", "").startswith(prefix)
            ),
            None,
        )
        if reason is None or not self.active or self.active["envelope"]["action"]["kind"] != "move":
            return False
        committed = (
            self.motion_remaining is not None
            and self.trajectory is not None
            and self.segment_remaining == self.motion_remaining
            and self.stream_expected == self.observation
            and self._segment_boundary() == self.motion_origin
        )
        retry = (
            self.motion_attempt < MAX_MOTION_ATTEMPTS
            and (self.observation == self.motion_origin or committed)
            and self.clock() - self.motion_started_at < 60
        )
        with (self.worker.output / f"{self.job_id}-rejection.json").open(
            "x", encoding="utf-8"
        ) as stream:
            json.dump(
                {
                    "request_id": self.active["request_id"],
                    "job_id": self.job_id,
                    "generation_attempt": self.motion_attempt,
                    "error": item["error"],
                    "retry": retry,
                    "played": False,
                },
                stream,
            )
        if retry:
            self._submit_motion(*self.motion_spec)
            self.message = (
                f"Nouvel essai du mouvement ({self.motion_attempt}/{MAX_MOTION_ATTEMPTS}) "
                f"après {reason}."
            )
        return retry

    def _target_tolerance(self):
        if self.active and self.active["envelope"]["action"]["kind"] == "move":
            return FREE_WALK_TARGET_TOLERANCE_M
        return DEFAULT_TARGET_TOLERANCE_M

    def _result(self, item):
        if item["job_id"] != self.job_id:
            return  # Cancelled generation: retained locally, never played later.
        if self.clock() - self.motion_started_at > 60:
            if not self.active:
                raise TimeoutError("Motion initialization generation exceeded 60 seconds.")
            self._feedback("failed", "Motion generation exceeded its 60-second budget.")
            return
        if self.motion_remaining is not None:
            self._stream_event(
                "generation_returned",
                job_id=item["job_id"],
                elapsed_seconds=self.clock() - self.job_started,
                worker_seconds=item.get("elapsed_seconds"),
                result=item["type"],
                continuation=item.get("continuation"),
            )
        if item["type"] == "error" and self._retry_motion_quality(item):
            return
        try:
            if item["type"] == "error":
                raise ValueError(item["error"])
            expected_file = f"{self.job_id}-processed.npz"
            if item.get("file") != expected_file:
                raise ValueError("Unexpected trajectory filename.")
            target = self.observation["avatar"]["position"]
            if self.motion_remaining is not None:
                target = self.motion_spec[0]
            if self.active and self.active["envelope"]["action"]["kind"] == "move":
                target = self.active["envelope"]["action"]["args"]["position"]
            poses = read_trajectory(
                self.worker.output / expected_file,
                start_pose=self.motion_origin["pose"]
                if self.motion_remaining is not None
                else self.pose,
                target=None
                if self.motion_remaining is not None and self.motion_remaining > 40
                else target,
                target_tolerance_m=self._target_tolerance(),
            )
            if self.motion_remaining is not None:
                if len(poses) != 41:
                    raise ValueError(
                        "Continuous playback requires an origin and exactly 40 future poses."
                    )
                if poses[0] != self.motion_origin["pose"]:
                    raise ValueError("Continuous origin differs from the observed Core pose.")
            if self.observation["objects"]:
                from promethee.object_actions import check_clearance
                from promethee.spatial import follow_attachment

                for pose in poses:
                    candidate = copy.deepcopy(
                        self.motion_origin
                        if self.motion_remaining is not None
                        else self.observation
                    )
                    candidate["pose"] = pose
                    held = candidate["avatar"]["holding"]
                    if held:
                        if self.arm_reach_check is not None and self.appearance_preparation is None:
                            self.arm_reach_check(
                                pose,
                                self.skeleton,
                                candidate["objects"][held]["spatial"]["attachment"]["joint"],
                            )
                        candidate["objects"][held] = follow_attachment(
                            candidate["objects"][held], pose
                        )
                    check_clearance(candidate)
        except (ValueError, OSError, KeyError) as exc:
            if not self.active:
                raise RuntimeError(f"Cannot initialize the body: {exc}") from exc
            self._feedback("failed", str(exc))
            return
        if self.appearance_preparation is not None:
            try:
                self._prepare_appearance(
                    poses if self.ready else poses[:1],
                    contacts=read_contact_flags(self.worker.output / expected_file)
                    if self.ready
                    else None,
                    origin=self.motion_origin if self.motion_remaining is not None else None,
                    remaining=self.motion_remaining - 40
                    if self.motion_remaining is not None
                    else None,
                )
            except (ValueError, OSError, KeyError) as exc:
                if not self.active:
                    raise RuntimeError(f"Cannot initialize the visible body: {exc}") from exc
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
            if self.motion_remaining is not None:
                self.job_id = None
                try:
                    self._accept_segment(
                        poses, None, self.motion_origin, self.motion_remaining - 40
                    )
                except ValueError as exc:
                    self._feedback("failed", str(exc))
                return
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
                self.skeleton = item["skeleton"]
                (self.worker.output / "conventions.json").write_text(
                    json.dumps(item["skeleton"]), encoding="utf-8"
                )
                if self.pose is not None:
                    held = self.observation["avatar"]["holding"]
                    if (
                        held
                        and self.arm_reach_check is not None
                        and self.appearance_preparation is None
                    ):
                        self.arm_reach_check(
                            self.pose,
                            self.skeleton,
                            self.observation["objects"][held]["spatial"]["attachment"]["joint"],
                        )
                    if (
                        self.appearance_preparation is not None
                        and self.observation.get("appearance") is None
                    ):
                        self._prepare_appearance([self.pose])
                        continue
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
        if self.appearance_preparation is not None:
            while item := self.appearance_preparation.poll():
                self._appearance_result(item)
        now = self.clock()
        if not self.ready and now - self.started_at > 180:
            raise TimeoutError("Motion initialization exceeded 180 seconds.")
        if self.worker.pending is not None and now - self.motion_started_at > 60:
            raise TimeoutError("Motion generation exceeded 60 seconds.")
        if self.trajectory is not None:
            if self.stream_expected is not None and self.observation != self.stream_expected:
                self._feedback("failed", "The body changed outside the committed motion stream.")
                return
            if self.object_frames is not None and self.observation != self.object_expected:
                self._feedback(
                    "failed", "The object or body changed during its planned interaction."
                )
                return
            self.frame = min(int((now - self.play_started) * 20), len(self.trajectory) - 1)
            if self.object_frames is not None:
                self.observation = copy.deepcopy(self.object_frames[self.frame])
            else:
                self._observe_pose(self.trajectory[self.frame])
            if self.appearance_frames is not None:
                self.observation["appearance"] = copy.deepcopy(self.appearance_frames[self.frame])
            if self.object_frames is not None:
                self.object_expected = copy.deepcopy(self.observation)
            if self.continuous_motion:
                self.history.record(self.pose, now)
            if self.stream_expected is not None:
                self.stream_expected = copy.deepcopy(self.observation)
            if self.frame == len(self.trajectory) - 1:
                if self.segment_remaining:
                    self.trajectory = self.appearance_frames = None
                    if self.future_segment is not None:
                        segment, self.future_segment = self.future_segment, None
                        try:
                            self._start_segment(segment)
                        except ValueError as exc:
                            self._feedback("failed", str(exc))
                    else:
                        self.message = "Attente de la suite du mouvement validée."
                        self._stream_event("buffer_empty")
                        self._feedback("running")
                    return
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
        if self.ready and self.continuous_motion:
            self.history.record(self.pose, now)
        if (
            self.ready
            and self.active is None
            and self.worker.pending is None
            and (self.appearance_preparation is None or self.appearance_preparation.pending is None)
        ):
            self.active = self.handle.claim_next()
            if self.active:
                self.motion_attempt = 0
                self.sequence = 0
                self._feedback("running")
                action = self.active["envelope"]["action"]
                if action["kind"] in {"spawn", "take", "place"}:
                    from promethee.object_actions import prepare_object_action
                    from promethee.world import validate_body_action

                    try:
                        validate_body_action(self.observation, action)
                        frames = prepare_object_action(
                            {key: self.observation[key] for key in ("avatar", "objects", "pose")},
                            self.skeleton,
                            action,
                            arm_reach_check=self.arm_reach_check,
                        )
                    except (ValueError, KeyError) as exc:
                        self._feedback("failed", str(exc))
                        return
                    if self.appearance_preparation is not None:
                        if action["kind"] != "spawn":
                            self._prepare_appearance(
                                [frame["pose"] for frame in frames],
                                frames,
                                stationary_support=True,
                            )
                            return
                        # Spawning changes only objects: retain the exact observed body.
                        for frame in frames:
                            frame["appearance"] = copy.deepcopy(self.observation["appearance"])
                    self.object_frames = frames
                    self.object_expected = copy.deepcopy(self.observation)
                    self.trajectory = [frame["pose"] for frame in frames]
                    self.frame = 0
                    self.play_started = self.clock()
                    self.message = "Interaction cinématique en cours."
                    return
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
                try:
                    self.worker.close()
                finally:
                    if self.appearance_preparation is not None:
                        self.appearance_preparation.close()
