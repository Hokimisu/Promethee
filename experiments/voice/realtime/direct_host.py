"""Opt-in direct-loop experiment using the existing turn host and process ownership."""

import sys
from contextlib import contextmanager
from pathlib import Path

from promethee.chat import ResidentProcess, TextHost, exclusive_host
from promethee.conversation import ConversationStore
from promethee.execution import ExecutionService
from promethee.runtime import Runtime


@contextmanager
def open_direct_host(args, *, auth_file):
    data_dir = args.data_dir.resolve()
    store = ConversationStore(ExecutionService(Runtime(data_dir / "world.sqlite3", create=False)))

    def factory(request, *, preparing=False):
        setup = (
            request
            if preparing
            else {
                **{k: v for k, v in request.items() if k not in {"message", "history"}},
                "standby_seconds": 120,
            }
        )
        process = ResidentProcess(
            [
                sys.executable,
                "-X",
                "utf8",
                str(Path(__file__).with_name("direct_worker.py")),
                "--data-dir",
                str(data_dir),
                "--auth-file",
                str(Path(auth_file).resolve()),
            ],
            setup,
            lifetime=setup["standby_seconds"],
        )
        if not preparing:
            process.activate(request)
        return process

    with exclusive_host(data_dir):
        host = TextHost(
            store,
            factory,
            model=args.model,
            base_url="https://chatgpt.com/backend-api/codex",
            api_mode="codex_responses",
            timeout=args.timeout,
            reasoning_effort=args.reasoning_effort,
            measure_timing=True,
            prewarm_factory=lambda request: factory(request, preparing=True),
            system_message=args.system_message,
            resident=True,
        )
        try:
            host.warm()
            yield host
        finally:
            host.close()
