import copy

import pytest

from promethee.execution import ExecutionService
from promethee.runtime import Runtime
from promethee.world import ACTION_FIELDS, apply


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeBody:
    """Deterministic CPU driver used only by tests; never an application backend."""

    def __init__(self, service):
        self.service = service
        self.handle = service.acquire_controller(
            source="logical-test", supported_actions=list(ACTION_FIELDS)
        )
        state = service.runtime.snapshot()
        self.observation = {key: copy.deepcopy(state[key]) for key in ("avatar", "objects")}
        assert self.handle.reconcile(self.observation, stopped=True)

    def start(self):
        item = self.handle.claim_next()
        assert item is not None
        assert self.handle.feedback(item["request_id"], 0, "running")
        return item

    def complete(self, item, sequence=1):
        candidate = copy.deepcopy(self.observation)
        apply(candidate, item["envelope"]["action"])
        result = self.handle.feedback(
            item["request_id"], sequence, "completed", observation=candidate
        )
        if result:
            self.observation = candidate
        return result


@pytest.fixture
def body(tmp_path):
    clock = Clock()
    runtime = Runtime(tmp_path / "body.sqlite3")
    service = ExecutionService(runtime, clock=clock)
    return service, FakeBody(service), clock
