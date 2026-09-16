"""Native Hermes conversation calls in an isolated Python environment.

stdin/stdout carry bounded JSON requests/results. The trusted host owns turn
creation, profile selection, deadlines, cancellation and history persistence.
Cold and prepared workers exit after one turn; resident mode is explicit.
"""

import argparse
import contextlib
import copy
import importlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from time import perf_counter, time

if __package__:
    from .hermes_adapter import validate_chat_options
else:
    from hermes_adapter import validate_chat_options


@contextlib.contextmanager
def elapsed(timings, name):
    if timings is None:
        yield
        return
    started = perf_counter()
    try:
        yield
    finally:
        timings[name] = perf_counter() - started


class RedactedLog:
    def __init__(self, stream, key):
        self.stream, self.key = stream, key

    def write(self, text):
        return self.stream.write(text.replace(self.key, "[credential redacted]"))

    def flush(self):
        self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[credential redacted]")
    if isinstance(value, list):
        return [redact(item, key) for item in value]
    if isinstance(value, dict):
        return {name: redact(item, key) for name, item in value.items()}
    return value


def read_request(*, preparing=False):
    line = sys.stdin.readline(1_048_577)
    if len(line) > 1_048_576 or not line.endswith("\n"):
        raise ValueError("Oversized or incomplete conversation request.")
    request = json.loads(line)
    required = {"turn_id", "model", "base_url", "api_mode", "session_id"}
    required |= {"standby_seconds"} if preparing else {"message", "history"}
    optional = {"reasoning_effort", "measure_timing", "system_message"}
    if (
        not isinstance(request, dict)
        or not required <= set(request)
        or not set(request) <= required | optional
    ):
        raise ValueError("Unexpected conversation request fields.")
    validate_chat_options(request.get("reasoning_effort"), request.get("measure_timing", False))
    for field in ("turn_id", "model", "base_url", "api_mode", "session_id"):
        if not isinstance(request[field], str) or not 1 <= len(request[field]) <= 2048:
            raise ValueError("Expected explicit bounded conversation identifiers.")
    if "system_message" in request and (
        not isinstance(request["system_message"], str)
        or not request["system_message"].strip()
        or len(request["system_message"]) > 16000
    ):
        raise ValueError("Expected a nonempty system message of at most 16000 characters.")
    if preparing:
        ttl = request["standby_seconds"]
        if (
            not re.fullmatch(r"turn-[0-9a-f]{32}", request["turn_id"])
            or type(ttl) not in (int, float)
            or not 0 < ttl <= 300
        ):
            raise ValueError("Invalid future turn or preparation lifetime.")
    elif (
        not isinstance(request["message"], str)
        or not request["message"].strip()
        or len(request["message"]) > 16000
        or not isinstance(request["history"], list)
    ):
        raise ValueError("Expected a bounded message and native conversation history.")
    return request


def verify_prepared_session(params, request, *, active=False):
    """Read-only independent guard: preparation conveys no turn authority."""
    index = params.index("--data-dir")
    database = (Path(params[index + 1]) / "world.sqlite3").resolve()
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as conn:
        world = json.loads(conn.execute("SELECT data FROM world WHERE id=1").fetchone()[0])
    if world["world_id"] != request["session_id"] or world["data_origin"] != "session":
        raise ValueError("Prepared worker belongs to another world session.")
    turn = world.get("conversation")
    if active and (
        not turn or turn["turn_id"] != request["turn_id"] or time() >= turn["expires_at"]
    ):
        raise ValueError("Prepared turn has not been activated or is no longer current.")


def resident_loop(agent, setup, *, profile, config_text, key, provider, protocol, timings, started):
    """Serialize host requests around the native Hermes loop, never own reasoning/history."""
    from hermes_adapter import refresh_resident_agent, resolve_hermes_codex_credentials

    stable = {k: v for k, v in setup.items() if k not in {"standby_seconds", "turn_id"}}
    schemas = copy.deepcopy(agent.tools)
    used = set()
    expiry = started + setup["standby_seconds"]
    first_timings = dict(timings or {})
    first_timings["prewarm_seconds"] = perf_counter() - started
    protocol.write(
        json.dumps(
            {
                "type": "ready",
                "turn_id": setup["turn_id"],
                "session_id": setup["session_id"],
            }
        )
        + "\n"
    )
    protocol.flush()
    try:
        while True:
            waiting = perf_counter()
            request = read_request()
            activated = perf_counter()
            measured = dict(first_timings) if not used else {}
            measured["standby_wait_seconds"] = activated - waiting
            turn_id = request["turn_id"]
            if (
                activated >= expiry
                or not re.fullmatch(r"turn-[0-9a-f]{32}", turn_id)
                or turn_id in used
                or (not used and turn_id != setup["turn_id"])
                or {k: v for k, v in request.items() if k not in {"turn_id", "message", "history"}}
                != stable
                or (profile / "config.yaml").read_text(encoding="utf-8") != config_text
            ):
                raise ValueError("Resident request changed identity, settings or profile.")
            config = json.loads(config_text)
            params = config["mcp_servers"]["promethee"]["args"]
            verify_prepared_session(params, request, active=True)
            with elapsed(measured, "auth_recheck_seconds"):
                fresh = resolve_hermes_codex_credentials(
                    model=request["model"],
                    base_url=request["base_url"],
                    api_mode=request["api_mode"],
                )
                if fresh["api_key"] != key:
                    raise ValueError("Resident authentication changed; create a new instance.")
            with elapsed(measured, "mcp_rebind_seconds"):
                refresh_resident_agent(
                    agent,
                    settings=stable,
                    provider=provider,
                    api_key=key,
                    schemas=schemas,
                    memory_enabled="--vault" in params,
                    call_authority=True,
                )
            used.add(turn_id)
            with elapsed(measured, "run_conversation_seconds"):
                result = agent.run_conversation(
                    request["message"],
                    conversation_history=request["history"],
                    task_id=turn_id,
                    **(
                        {"system_message": request["system_message"]}
                        if "system_message" in request
                        else {}
                    ),
                )
            if agent.session_id != stable["session_id"]:
                raise ValueError("Native session changed during the resident turn.")
            if not isinstance(result, dict) or not isinstance(result.get("messages"), list):
                raise ValueError("Hermes returned an unexpected resident result.")
            response = {
                "type": "result",
                "turn_id": turn_id,
                "messages": result["messages"],
                "text": result.get("final_response"),
                "interrupted": bool(result.get("interrupted")),
                "failed": bool(result.get("error") or result.get("failed") or result.get("partial"))
                or result.get("completed") is False,
            }
            if setup.get("measure_timing"):
                response["timings"] = {
                    **measured,
                    "activation_seconds": perf_counter() - activated,
                    "worker_total_seconds": perf_counter() - started,
                }
            encoded = json.dumps(redact(response, key), ensure_ascii=False, allow_nan=False)
            if len(encoded) > 4_194_304:
                raise ValueError("Oversized resident result.")
            protocol.write(encoded + "\n")
            protocol.flush()
            if response["failed"] or response["interrupted"]:
                return
            expiry = perf_counter() + setup["standby_seconds"]
    finally:
        agent.close()


def main():
    worker_started = perf_counter()
    timings = None

    def measured(response):
        if timings is not None:
            response["timings"] = {
                **timings,
                "worker_total_seconds": perf_counter() - worker_started,
            }
        return response

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-root", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--auth", choices=["api-key", "hermes-codex"], default="api-key")
    parser.add_argument("--prewarm", action="store_true")
    parser.add_argument("--resident", action="store_true")
    args = parser.parse_args()
    profile = args.profile.resolve()
    hermes_root = args.hermes_root.resolve()
    protocol = sys.stdout
    key = os.environ.get("PROMETHEE_OPENAI_API_KEY")
    if not key and args.auth == "api-key":
        protocol.write(json.dumps({"type": "error", "code": "credentials_missing"}) + "\n")
        return
    try:
        if args.resident and (args.auth != "hermes-codex" or args.prewarm):
            raise ValueError(
                "Resident mode requires native Codex authentication and its own preparation."
            )
        request = read_request(preparing=args.prewarm or args.resident)
        reasoning_effort = request.get("reasoning_effort")
        measure_timing = request.get("measure_timing", False)
        validate_chat_options(reasoning_effort, measure_timing)
        if measure_timing:
            timings = {"auth_seconds": 0.0}
        # Profile JSON is also valid YAML; this worker accepts only the exact
        # host-generated shape, never a personal Hermes config or its secrets.
        config_text = (profile / "config.yaml").read_text(encoding="utf-8")
        config = json.loads(config_text)
        params = config["mcp_servers"]["promethee"]["args"]
        call_authority = params[-1:] == ["--call-authority"] and "--turn-id" not in params
        if call_authority != args.resident:
            raise ValueError("Per-call MCP authority and resident mode must be enabled together.")
        if not call_authority and params[-2:] != ["--turn-id", request["turn_id"]]:
            raise ValueError("The MCP profile is not bound to this conversation turn.")
        if args.prewarm or args.resident:
            verify_prepared_session(params, request)
        os.environ["HERMES_HOME"] = str(profile)
        os.chdir(profile)
        sys.path.insert(0, str(hermes_root))
        provider = "openai"
        if args.auth == "hermes-codex":
            # The native profile path inherits authentication through Hermes,
            # while config, context and memory remain in this fresh profile.
            if profile.parent.name != "profiles":
                raise ValueError("Hermes authentication requires a native dedicated profile.")
            with elapsed(timings, "auth_seconds"), contextlib.redirect_stdout(sys.stderr):
                from hermes_adapter import resolve_hermes_codex_credentials

                credentials = resolve_hermes_codex_credentials(
                    model=request["model"],
                    base_url=request["base_url"],
                    api_mode=request["api_mode"],
                )
            key = credentials["api_key"]
            provider = credentials["provider"]
        log = RedactedLog(sys.stderr, key)
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            with elapsed(timings, "import_seconds"):
                from hermes_adapter import create_agent
                from tools.mcp_tool import shutdown_mcp_servers

                if measure_timing:
                    # Separate the expensive native import from construction.
                    # Credential resolver imports remain part of auth_seconds.
                    importlib.import_module("run_agent")

            try:
                with elapsed(timings, "agent_construct_seconds"):
                    agent = create_agent(
                        model=request["model"],
                        api_key=key,
                        base_url=request["base_url"],
                        api_mode=request["api_mode"],
                        session_id=request["session_id"],
                        memory_enabled="--vault" in params,
                        provider=provider,
                        call_authority=call_authority,
                        **(
                            {"reasoning_effort": reasoning_effort}
                            if reasoning_effort is not None
                            else {}
                        ),
                    )
                if args.resident:
                    resident_loop(
                        agent,
                        request,
                        profile=profile,
                        config_text=config_text,
                        key=key,
                        provider=provider,
                        protocol=protocol,
                        timings=timings,
                        started=worker_started,
                    )
                    return
                if args.prewarm:
                    prepared = {k: v for k, v in request.items() if k != "standby_seconds"}
                    expires_at = worker_started + request["standby_seconds"]
                    if timings is not None:
                        timings["prewarm_seconds"] = perf_counter() - worker_started
                    protocol.write(
                        json.dumps(
                            {
                                "type": "ready",
                                "turn_id": request["turn_id"],
                                "session_id": request["session_id"],
                            }
                        )
                        + "\n"
                    )
                    protocol.flush()
                    with elapsed(timings, "standby_wait_seconds"):
                        request = read_request()
                    activation_started = perf_counter()
                    if (
                        perf_counter() >= expires_at
                        or {k: v for k, v in request.items() if k not in {"message", "history"}}
                        != prepared
                        or (profile / "config.yaml").read_text(encoding="utf-8") != config_text
                    ):
                        raise ValueError("Prepared worker settings changed or expired.")
                    verify_prepared_session(params, request, active=True)
                    with elapsed(timings, "auth_recheck_seconds"):
                        if args.auth == "hermes-codex":
                            refreshed = resolve_hermes_codex_credentials(
                                model=request["model"],
                                base_url=request["base_url"],
                                api_mode=request["api_mode"],
                            )
                            if refreshed["api_key"] != key:
                                raise ValueError(
                                    "Prepared native authentication changed; prepare again."
                                )
                with elapsed(timings, "run_conversation_seconds"):
                    result = agent.run_conversation(
                        request["message"],
                        conversation_history=request["history"],
                        task_id=request["turn_id"],
                        **(
                            {"system_message": request["system_message"]}
                            if "system_message" in request
                            else {}
                        ),
                    )
            finally:
                with elapsed(timings, "mcp_shutdown_seconds"):
                    shutdown_mcp_servers()
        if args.prewarm and timings is not None:
            timings["activation_seconds"] = perf_counter() - activation_started
        if not isinstance(result, dict) or not isinstance(result.get("messages"), list):
            raise ValueError("Hermes returned an unexpected conversation result.")
        response = {
            "type": "result",
            "turn_id": request["turn_id"],
            "messages": result.get("messages", []),
            "text": result.get("final_response"),
            "interrupted": bool(result.get("interrupted")),
            "failed": bool(result.get("error") or result.get("failed") or result.get("partial"))
            or result.get("completed") is False,
        }
        encoded = json.dumps(redact(measured(response), key), ensure_ascii=False, allow_nan=False)
        if len(encoded) > 4_194_304:
            raise ValueError("Oversized conversation result.")
        protocol.write(encoded + "\n")
    except Exception as exc:
        # Provider exceptions can quote credentials. Never return their raw text.
        protocol.write(
            json.dumps(
                measured(
                    {
                        "type": "error",
                        "code": "conversation_failed",
                        "exception": type(exc).__name__,
                    }
                )
            )
            + "\n"
        )
    protocol.flush()


if __name__ == "__main__":
    main()
