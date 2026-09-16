"""Explicit experimental ARDY presence; never creates an agent execution.

The owner calls set_presence on its body-loop thread. Generation and preparation
may run ahead, but only played observations enter the world. Failed presence is
latched until False -> True. The regular KinematicController remains unchanged.
"""

import copy
import json
import math
from contextlib import contextmanager
from uuid import uuid4

from promethee.kinematic import FREE_WALK_TARGET_TOLERANCE_M, KinematicController
from promethee.motion_history import write_history
from promethee.world import ActionError

PRESENCE_TEXT = "A person stands in place and speaks with natural expressive hand gestures."


class PresenceController(KinematicController):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.presence_enabled = False
        self.presence_status = "disabled"
        self.presence_error = None
        self._presence_job = None
        self._presence_preparation = None
        self._presence_stream = None
        self._presence_anchor = None
        self._presence_segment = None
        self._presence_future = None
        self._presence_frame = -1
        self._routing_presence = False
        self._discarded_presence_jobs = set()
        self._discarded_presence_preparations = set()

    def set_presence(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("Presence must be explicitly enabled or disabled.")
        if self.closed:
            raise RuntimeError("Controller is closed.")
        if enabled == self.presence_enabled:
            return
        self.presence_enabled = enabled
        if enabled:
            self.presence_error = None
            self.presence_status = "waiting"
        else:
            self._discard_presence("disabled")

    def _foreground_pending(self):
        with self.service.runtime.connection() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM executions WHERE status IN ('accepted','running') LIMIT 1"
                ).fetchone()
                is not None
            )

    def _discard_presence(self, status):
        if self._presence_job is not None:
            self._discarded_presence_jobs.add(self._presence_job["job_id"])
        if self._presence_preparation is not None:
            self._discarded_presence_preparations.add(self._presence_preparation)
            if self.appearance_job == self._presence_preparation:
                self.appearance_preparation.cancel()
                self.appearance_job = self.preparation = None
        self._presence_job = self._presence_preparation = None
        self._presence_segment = self._presence_future = None
        self._presence_stream = self._presence_anchor = None
        self._presence_frame = -1
        self.presence_status = status

    def _presence_failed(self, error):
        self.presence_error = str(error)
        self._discard_presence("failed")
        self.message = "Gestes de présence suspendus : " + self.presence_error

    def _submit_presence(self, origin=None, context=None):
        origin = copy.deepcopy(self.observation if origin is None else origin)
        if self._presence_anchor is None:
            self._presence_anchor = copy.deepcopy(origin["avatar"]["position"])
        job_id = uuid4().hex
        if self._presence_stream is None:
            self._presence_stream = uuid4().hex
        if context is None:
            self.history.record(self.pose, self.clock())
            context = self.history.context()
        poses, committed = context
        job = {
            "job_id": job_id,
            "target": copy.deepcopy(self._presence_anchor),
            "text": PRESENCE_TEXT,
            "seed": self.seed,
            "frames": 40,
            "future_frames": 40,
            "stream_id": self._presence_stream,
            "start_pose": origin["pose"],
            "posture": None,
            "history": write_history(self.worker.output, job_id, poses, committed),
        }
        with (self.worker.output / f"{job_id}-request.json").open("x", encoding="utf-8") as stream:
            json.dump(
                {
                    "world_id": self.world_id,
                    "controller_session": self.handle.session_id,
                    "request_id": None,
                    "purpose": "body-presence",
                    "source": "kinematic",
                    "job": job,
                },
                stream,
                allow_nan=False,
            )
        self.worker.submit(job)
        self.seed = (self.seed + 1) % (2**31)
        started = self.clock()
        self._presence_job = {**job, "origin": origin, "started": started}
        # The base timeout also observes the shared worker. It must use this job's
        # actual start, not the timestamp of an old foreground action.
        self.motion_started_at = started
        self.presence_status = "playing" if self._presence_segment else "generating"

    @contextmanager
    def _presence_motion_fields(self, job):
        fields = {
            "job_id": job["job_id"],
            "motion_origin": job["origin"],
            "motion_remaining": 40,
            "motion_spec": (job["target"], PRESENCE_TEXT, 40),
            "motion_started_at": job["started"],
            "job_started": job["started"],
        }
        previous = {name: getattr(self, name, None) for name in fields}
        try:
            for name, value in fields.items():
                setattr(self, name, value)
            self._routing_presence = True
            yield
        finally:
            self._routing_presence = False
            for name, value in previous.items():
                setattr(self, name, value)

    def _result(self, item):
        if item["job_id"] in self._discarded_presence_jobs:
            self._discarded_presence_jobs.discard(item["job_id"])
            return
        job = self._presence_job
        if job is None or item["job_id"] != job["job_id"]:
            return super()._result(item)
        if not self.presence_enabled or self._foreground_pending():
            self._discard_presence("preempted" if self.presence_enabled else "disabled")
            self._discarded_presence_jobs.discard(item["job_id"])
            return
        try:
            # Reuse the exact Core continuity, support, object and
            # appearance preparation gates. active stays None throughout.
            with self._presence_motion_fields(job):
                super()._result(item)
            self._presence_job = None
            self._presence_preparation = self.appearance_job
            self.presence_status = "playing" if self._presence_segment else "preparing"
        except (RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
            self._presence_failed(exc)

    def _target_tolerance(self):
        if self._routing_presence:
            return FREE_WALK_TARGET_TOLERANCE_M
        return super()._target_tolerance()

    def _appearance_result(self, item):
        if item["job_id"] in self._discarded_presence_preparations:
            self._discarded_presence_preparations.discard(item["job_id"])
            return
        if item["job_id"] != self._presence_preparation:
            return super()._appearance_result(item)
        if not self.presence_enabled or self._foreground_pending():
            self._discard_presence("preempted" if self.presence_enabled else "disabled")
            self._discarded_presence_preparations.discard(item["job_id"])
            return
        try:
            self._routing_presence = True
            super()._appearance_result(item)
            self._presence_preparation = None
        except (RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
            self._presence_failed(exc)
        finally:
            self._routing_presence = False

    def _accept_segment(self, poses, appearances, origin, remaining):
        if not self._routing_presence:
            return super()._accept_segment(poses, appearances, origin, remaining)
        if appearances is None:
            raise ValueError("Presence requires a validated visible appearance.")
        segment = {"poses": poses, "appearances": appearances, "origin": copy.deepcopy(origin)}
        if self._presence_segment is None:
            self._start_presence_segment(segment)
        elif self._presence_future is None:
            self._presence_future = segment
        else:
            raise ValueError("A future presence horizon is already committed.")

    def _start_presence_segment(self, segment):
        if self.observation != segment["origin"]:
            raise ValueError("Presence boundary differs from the observed body.")
        self._presence_segment = segment
        self._presence_play_started = self.clock()
        self._presence_expected = copy.deepcopy(self.observation)
        self._presence_frame = 0
        self.presence_status = "playing"

    def _presence_boundary(self):
        # Same attachment-aware boundary helper used by foreground streams;
        # temporary fields never enter the world's observed checkpoint.
        trajectory, appearances = self.trajectory, self.appearance_frames
        try:
            self.trajectory = self._presence_segment["poses"]
            self.appearance_frames = self._presence_segment["appearances"]
            return self._segment_boundary()
        finally:
            self.trajectory, self.appearance_frames = trajectory, appearances

    def _play_presence(self, now):
        segment = self._presence_segment
        if segment is None:
            return
        if self.observation != self._presence_expected:
            raise ValueError("Body changed outside the presence stream.")
        frame = min(
            math.floor((now - self._presence_play_started) * 20 + 1e-6), len(segment["poses"]) - 1
        )
        if frame != self._presence_frame:
            before = copy.deepcopy(self.observation)
            self._observe_pose(segment["poses"][frame])
            self.observation["appearance"] = copy.deepcopy(segment["appearances"][frame])
            try:
                accepted = self.handle.observe_idle(self.observation)
            except ActionError:
                # An action may have been accepted after our read-only check.
                # Roll back before the publisher can see any uncommitted pose.
                self.observation = before
                if self._foreground_pending():
                    self._discard_presence("preempted")
                    return
                raise
            if not accepted:
                self.observation = before
                self._discard_presence("ownership-lost")
                raise RuntimeError("Presence observation lost controller ownership.")
            self._presence_frame = frame
            self._presence_expected = copy.deepcopy(self.observation)
            self.history.record(self.pose, now)
        if frame == len(segment["poses"]) - 1:
            self._presence_segment = None
            if self._presence_future is not None:
                future, self._presence_future = self._presence_future, None
                self._start_presence_segment(future)
            else:
                self.presence_status = "waiting"

    def tick(self):
        if self.presence_enabled and self._foreground_pending():
            self._discard_presence("preempted")
        if self._presence_job and self.clock() - self._presence_job["started"] > 60:
            self._presence_failed("Presence generation exceeded 60 seconds.")
        if self.worker.pending in self._discarded_presence_jobs:
            # ARDY has no per-job cancellation. Drain the invalidated result;
            # its independent presence deadline has already failed above.
            self.motion_started_at = self.clock()
        super().tick()
        if not self.presence_enabled or self.presence_error or not self.ready:
            return
        if self.active is not None or self._foreground_pending():
            self._discard_presence("preempted")
            return
        if self.appearance_preparation is None or self.observation.get("appearance") is None:
            self._presence_failed("Presence requires prepared appearance mode.")
            return
        try:
            self._play_presence(self.clock())
            if self.presence_status == "ownership-lost":
                return
            if self._foreground_pending():
                self._discard_presence("preempted")
                return
            if (
                self.worker.pending is None
                and self.appearance_preparation.pending is None
                and self._presence_future is None
            ):
                if self._presence_segment is None:
                    self._submit_presence()
                else:
                    self._submit_presence(
                        self._presence_boundary(),
                        self.history.context(self._presence_segment["poses"][1:]),
                    )
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self._presence_failed(exc)

    def close(self):
        if not self.closed:
            self.presence_enabled = False
            self._discard_presence("disabled")
        super().close()
