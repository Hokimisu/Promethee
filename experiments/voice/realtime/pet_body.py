"""Pet-specific manipulation on the single ARDY controller owner thread."""

import copy

from presence import PresenceController

from promethee.kinematic import MAX_MOTION_ATTEMPTS, POSTURE_TEXT, RETRYABLE_MOTION_ERRORS
from promethee.motion_history import ExecutedHistory
from promethee.pet_world import PetWorld


class PetController(PresenceController):
    def __init__(self, *args, **kwargs):
        kwargs["object_interactions"] = True
        super().__init__(*args, **kwargs)
        self.pet = PetWorld(self.service, self.handle)
        self.viewing = False
        self.presence_text = POSTURE_TEXT["standing"]
        self._physics_at = self.clock()
        self._intervention_fault = None
        self._presence_quality_failures = 0
        self._presence_retry_at = None

    def _reset_presence_retry(self):
        self._presence_quality_failures = 0
        self._presence_retry_at = None

    def _presence_failed(self, error):
        super()._presence_failed(error)
        self._presence_retry_at = None
        # Core worker quality refusals are wrapped by KinematicController.
        # Do not turn arbitrary runtime/storage errors into generation retries.
        cause = error.__cause__ if isinstance(error, RuntimeError) else error
        if not isinstance(cause, ValueError) or not str(cause).startswith(
            tuple(RETRYABLE_MOTION_ERRORS)
        ):
            return
        self._presence_quality_failures += 1
        if self._presence_quality_failures < MAX_MOTION_ATTEMPTS:
            self._presence_retry_at = self.clock() + 1.0
            self.presence_status = "retry-wait"

    def _play_presence(self, now):
        segment, frame = self._presence_segment, self._presence_frame
        super()._play_presence(now)
        if (
            segment is not None
            and self.presence_status in {"playing", "waiting"}
            and (self._presence_segment is not segment or self._presence_frame != frame)
        ):
            # A generated/prepared future is not playback. The base method only
            # advances these fields after observe_idle accepts the visible pose.
            self._reset_presence_retry()

    def _stop_local(self):
        """Invalidate every future; late worker results are drained, never displayed."""
        if self.job_id is not None:
            self._discarded_presence_jobs.add(self.job_id)
        self._discard_presence("interrupted")
        if self.appearance_preparation is not None:
            if self.appearance_job is not None:
                self._discarded_presence_preparations.add(self.appearance_job)
            self.appearance_preparation.cancel()
        self.appearance_job = self.preparation = self.appearance_frames = None
        self.active = self.trajectory = self.job_id = None
        self.motion_origin = self.motion_spec = self.motion_context = None
        self.object_frames = self.object_expected = self.future_segment = None
        self.motion_remaining = self.stream_id = self.stream_expected = None
        self.motion_attempt = self.segment_remaining = 0
        self.history = ExecutedHistory()

    def set_viewing(self, viewing):
        if type(viewing) is not bool:
            raise ValueError("Viewing must be a boolean.")
        # Initialization is allowed while suspended; do not cancel its first pose.
        stopped = False

        def stop():
            nonlocal stopped
            if self.ready:
                stopped = True
                self._stop_local()

        try:
            self.pet.suspend(self.observation, stop, not viewing)
        except Exception:
            if stopped:
                # SQLite can roll back the pause, but cannot restart the local
                # driver we already stopped. Release ownership on the next tick.
                self._intervention_fault = (
                    "Viewing change could not be saved after stopping the body."
                )
            raise
        if viewing and not self.viewing:
            self._reset_presence_retry()
            self.presence_error = None
            self.presence_status = "waiting"
        self.viewing = viewing
        super().set_presence(viewing)
        self._physics_at = self.clock()

    def set_presence(self, enabled):
        # Speech delivery must not freeze a living scene when its audio ends.
        # The viewer/pause lease remains the authoritative switch for pet idle.
        super().set_presence(enabled or self.viewing)

    def intervene(self, value):
        if not self.ready:
            raise ValueError("Ariane's body is still loading.")
        stopped = False

        def stop():
            nonlocal stopped
            stopped = True
            self._stop_local()

        try:
            result = self.pet.apply(value, self.observation, stop)
        except Exception:
            if stopped:
                # A storage failure after local cancellation must not leave a
                # durable running action without its driver. Release ownership
                # on the next tick; restart reconciles the last committed pose.
                self._intervention_fault = (
                    "Intervention could not be saved after stopping the body."
                )
            raise
        if not result["replayed"]:
            self.observation = copy.deepcopy(result["observation"])
            self._reset_presence_retry()
            self.presence_error = None
            self.message = "Intervention appliquée."
        return result

    def tick(self):
        if self._intervention_fault:
            raise RuntimeError(self._intervention_fault)
        now = self.clock()
        dt = max(0, min(0.25, now - self._physics_at))
        self._physics_at = now
        state = self.service.runtime.snapshot()["sandbox"]
        airborne = (
            self.ready
            and self.active is None
            and any(
                obj["asset"] == "ball"
                and obj["spatial"]["attachment"] is None
                and obj["spatial"]["position"][1] > 0.060001
                for obj in self.observation["objects"].values()
            )
        )
        held = (
            state["grab"]
            or state["flights"]
            or airborne
            or self.observation["avatar"]["holding"]
            or not self.viewing
        )
        enabled = self.presence_enabled
        if (
            not held
            and enabled
            and self.ready
            and self._presence_retry_at is not None
            and now >= self._presence_retry_at
        ):
            self._presence_retry_at = None
            self.presence_error = None
            self.presence_status = "waiting"
        if held and self.ready:
            self._discard_presence("suspended")
            self.presence_enabled = False
        try:
            super().tick()
        finally:
            self.presence_enabled = enabled
        if self.ready:
            self.observation, _ = self.pet.physics(self.observation, dt, simulate=self.viewing)
