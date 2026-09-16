"""Small experimental Responses loop. No Hermes imports, prompts or agent runtime.

Uses the existing world tools in process and the host's durable turn fencing.
Authentication is read-only from the explicitly configured local OAuth store.
No refresh, fallback, automatic retry, memory extraction or context truncation.
"""

import argparse
import asyncio
import base64
import copy
import hashlib
import json
import os
import re
import sys
import time
from functools import partial
from pathlib import Path

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from promethee.conversation import bounded_history
from promethee.execution import ExecutionService
from promethee.mcp_server import create_server
from promethee.runtime import Runtime

ENDPOINT = "https://chatgpt.com/backend-api/codex"
PREFIX = "mcp__promethee__"
OUTPUT_FIELD = "promethee_responses_output"
TOOLS = {"read_world", "list_capabilities", "submit_action", "read_execution", "cancel_action"}


class ProviderFailure(ValueError):
    pass


def strict_json(text):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key.")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("Non-finite JSON value.")

    return json.loads(text, object_pairs_hook=object_pairs, parse_constant=constant)


def credentials(path, *, now=None):
    """Read the existing grant without rotating or copying its refresh token."""
    state = json.loads(Path(path).read_text(encoding="utf-8"))
    token = state["providers"]["openai-codex"]["tokens"]["access_token"]
    encoded = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    account = claims["https://api.openai.com/auth"]["chatgpt_account_id"]
    current = time.time() if now is None else now
    if not isinstance(account, str) or not account or claims["exp"] <= current + 30:
        raise ProviderFailure("authentication_expired")
    return token, account


def verify_turn(service, request):
    world = service.get_world()
    turn = world.get("conversation")
    if (
        world["world_id"] != request["session_id"]
        or not turn
        or turn["turn_id"] != request["turn_id"]
        or time.time() >= turn["expires_at"]
    ):
        raise ValueError("obsolete_turn")


def response_input(messages):
    """Preserve opaque reasoning and call IDs in our own explicitly marked history."""
    result = []
    for message in bounded_history(messages):
        if OUTPUT_FIELD in message:
            if message["role"] != "assistant" or not isinstance(message[OUTPUT_FIELD], list):
                raise ValueError("Invalid Responses history.")
            result.extend(copy.deepcopy(message[OUTPUT_FIELD]))
        elif message["role"] == "tool":
            result.append(
                {
                    "type": "function_call_output",
                    "call_id": message["tool_call_id"],
                    "output": message["content"],
                }
            )
        elif message.get("tool_calls") or not isinstance(message.get("content"), str):
            raise ValueError("Use a fresh qualification world for this harness.")
        else:
            result.append({"role": message["role"], "content": message["content"]})
    return result


def completed_response(lines, *, clock=time.perf_counter, began=None):
    """Only response.completed authorizes a result; deltas never dispatch tools/audio."""
    began = clock() if began is None else began
    metrics = {"first_event_seconds": None, "first_text_seconds": None}
    data = []
    size = 0
    response_id = None
    items = {}
    pending = set()
    for line in lines:
        size += len(line.encode("utf-8"))
        if size > 8_388_608:
            raise ProviderFailure("response_too_large")
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
            continue
        if line or not data:
            continue
        payload, data = "\n".join(data), []
        if payload == "[DONE]":
            break
        event = strict_json(payload)
        kind = event.get("type")
        if metrics["first_event_seconds"] is None:
            metrics["first_event_seconds"] = clock() - began
        if kind == "response.output_text.delta" and metrics["first_text_seconds"] is None:
            metrics["first_text_seconds"] = clock() - began
        if kind == "response.created":
            response_id = event["response"]["id"]
        if kind in {"response.output_item.added", "response.output_item.done"}:
            index = event.get("output_index")
            item = event.get("item")
            if type(index) is not int or not 0 <= index < 64 or not isinstance(item, dict):
                raise ProviderFailure("invalid_output_item")
            if kind == "response.output_item.added":
                if index in items or index in pending:
                    raise ProviderFailure("duplicate_output_item")
                pending.add(index)
            else:
                if index in items or item.get("status") in {"in_progress", "incomplete", "failed"}:
                    raise ProviderFailure("incomplete_output_item")
                items[index] = item
                pending.discard(index)
        if kind in {"error", "response.failed", "response.incomplete"}:
            raise ProviderFailure("provider_failed")
        if kind == "response.completed":
            response = event["response"]
            output = response.get("output")
            # Codex sends complete items on output_item.done and can finish with [].
            # Only settled complete items, followed by a valid terminal, may be used.
            if items:
                if set(items) != set(range(len(items))):
                    raise ProviderFailure("noncontiguous_output")
                settled = [items[index] for index in range(len(items))]
                if output == []:
                    output = settled
                elif isinstance(output, list) and output != settled:
                    raise ProviderFailure("conflicting_output")
            if (
                response.get("status") != "completed"
                or response.get("error")
                or response.get("incomplete_details")
                or not isinstance(output, list)
                or pending
                or any(
                    not isinstance(item, dict)
                    or item.get("status") in {"in_progress", "incomplete", "failed"}
                    for item in (output or [])
                )
                or (response_id is not None and response_id != response.get("id"))
            ):
                raise ProviderFailure("incomplete_response")
            metrics["completed_seconds"] = clock() - began
            metrics["usage"] = response.get("usage")
            return output, metrics
    raise ProviderFailure("missing_completed_event")


def provider_call(client, payload, token, account, session_id):
    began = time.perf_counter()
    headers = {
        "Authorization": "Bearer " + token,
        "ChatGPT-Account-ID": account,
        "User-Agent": "PrometheeExperiment/0.1",
        "originator": "promethee",
        "session_id": session_id,
        "Accept": "text/event-stream",
    }
    with client.stream("POST", ENDPOINT + "/responses", headers=headers, json=payload) as response:
        if response.status_code != 200:
            # Do not expose provider bodies, request headers or credentials in errors.
            raise ProviderFailure("provider_http_" + str(response.status_code))
        # This configured Codex route can omit Content-Type on otherwise valid SSE.
        # The same bounded event parser and terminal validation still apply.
        content_type = response.headers.get("content-type", "")
        if content_type and "text/event-stream" not in content_type:
            raise ProviderFailure("unexpected_content_type")
        return completed_response(response.iter_lines(), began=began)


def retained_output(output):
    """Keep encrypted reasoning for replay; never publish or persist reasoning summaries."""
    kept = copy.deepcopy(output)
    for item in kept:
        if item.get("type") == "reasoning":
            item["summary"] = []
            item.pop("content", None)
            item.pop("id", None)  # store:false has no durable reasoning item to look up.
    return kept


async def run_turn(service, request, call):
    verify_turn(service, request)
    server = create_server(service, turn_id=request["turn_id"])
    listed = await server.list_tools()
    if {tool.name for tool in listed} != TOOLS:
        raise ValueError("Unexpected tool scope.")
    schemas = {tool.name: tool.input_schema for tool in listed}
    tools = [
        {
            "type": "function",
            "name": PREFIX + tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
            "strict": False,
        }
        for tool in listed
    ]
    instructions = request["system_message"] + "\n" + server.instructions
    messages = copy.deepcopy(request["history"])
    messages.append({"role": "user", "content": request["message"]})
    cache_key = hashlib.sha256(
        json.dumps([request["session_id"], instructions, tools]).encode()
    ).hexdigest()
    timings = {"backend": "direct-responses", "provider_calls": [], "tool_calls": []}
    started = time.perf_counter()
    used_calls = set()
    for _ in range(8):
        verify_turn(service, request)
        payload = {
            "model": request["model"],
            "instructions": instructions,
            "input": response_input(messages),
            "tools": tools,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "reasoning": {"effort": request["reasoning_effort"]},
            "include": ["reasoning.encrypted_content"],
            "store": False,
            "stream": True,
            "prompt_cache_key": cache_key,
        }
        output, measure = call(payload)
        verify_turn(service, request)
        timings["provider_calls"].append(measure)
        output = retained_output(output)
        calls = [item for item in output if item.get("type") == "function_call"]
        if len(calls) > 8 or any(
            item.get("type") not in {"function_call", "message", "reasoning"} for item in output
        ):
            raise ProviderFailure("unsupported_output")
        text = "".join(
            part["text"]
            for item in output
            if item.get("type") == "message"
            and item.get("channel") in {None, "final"}
            and item.get("phase") in {None, "final", "final_answer"}
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )
        messages.append({"role": "assistant", "content": text, OUTPUT_FIELD: output})
        if not calls:
            if not text.strip():
                shape = [
                    {
                        "type": item.get("type"),
                        "channel": item.get("channel"),
                        "phase": item.get("phase"),
                        "content_types": [p.get("type") for p in item.get("content", [])],
                    }
                    for item in output
                ]
                raise ProviderFailure("no_final_text:" + json.dumps(shape))
            timings["run_conversation_seconds"] = time.perf_counter() - started
            return {
                "type": "result",
                "turn_id": request["turn_id"],
                "messages": bounded_history(messages),
                "text": text,
                "failed": False,
                "interrupted": False,
                "timings": {"run_conversation_seconds": timings["run_conversation_seconds"]},
                "direct_metrics": timings,
            }
        ids = [item.get("call_id") for item in calls]
        if (
            any(not isinstance(value, str) or not value for value in ids)
            or len(set(ids)) != len(ids)
            or used_calls.intersection(ids)
        ):
            raise ProviderFailure("invalid_call_ids")
        used_calls.update(ids)
        for item in calls:
            verify_turn(service, request)
            began = time.perf_counter()
            name = item.get("name", "")
            bare = name.removeprefix(PREFIX)
            result = json.dumps({"error": "invalid_tool_arguments"})
            try:
                arguments = strict_json(item["arguments"])
                if (
                    name != PREFIX + bare
                    or bare not in TOOLS
                    or not isinstance(arguments, dict)
                    or arguments.keys() - schemas[bare].get("properties", {}).keys()
                ):
                    raise ValueError("Invalid tool call.")
                reply = await server.call_tool(bare, arguments)
                # Match the native MCP text surface without duplicating structuredContent.
                result = "\n".join(block.text for block in reply.content if block.type == "text")
                if not result:
                    result = json.dumps(reply.structured_content)
            except (ValueError, TypeError, KeyError, ToolError):
                pass
            timings["tool_calls"].append({"name": name, "seconds": time.perf_counter() - began})
            messages.append({"role": "tool", "tool_call_id": item["call_id"], "content": result})
    raise ProviderFailure("iteration_limit")


def read_frame():
    line = sys.stdin.readline(1_048_577)
    if len(line) > 1_048_576 or not line.endswith("\n"):
        raise ValueError("Invalid request frame.")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("Invalid request.")
    return value


def write_frame(value):
    text = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if len(text) > 4_194_304:
        raise ValueError("Response frame too large.")
    print(text, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--auth-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        setup = read_frame()
        stable = {k: v for k, v in setup.items() if k not in {"standby_seconds", "turn_id"}}
        if (
            setup.get("base_url") != ENDPOINT
            or setup.get("api_mode") != "codex_responses"
            or setup.get("model") not in {"gpt-5.6-luna", "gpt-6-astra"}
            or setup.get("reasoning_effort") != "low"
            or not isinstance(setup.get("system_message"), str)
            or not 0 < setup.get("standby_seconds", 0) <= 300
        ):
            raise ValueError("Unsupported experiment settings.")
        _, account = credentials(args.auth_file)
        service = ExecutionService(Runtime(args.data_dir / "world.sqlite3", create=False))
        if service.get_world()["world_id"] != setup["session_id"]:
            raise ValueError("Wrong world.")
        write_frame(
            {"type": "ready", "turn_id": setup["turn_id"], "session_id": setup["session_id"]}
        )
        expiry = time.perf_counter() + setup["standby_seconds"]
        used = set()
        with httpx.Client(timeout=60, follow_redirects=False) as client:
            while True:
                request = read_frame()
                activated = time.perf_counter()
                turn = request.get("turn_id")
                if (
                    activated >= expiry
                    or not isinstance(turn, str)
                    or re.fullmatch(r"turn-[a-f0-9]{32}", turn) is None
                    or turn in used
                    or (not used and turn != setup["turn_id"])
                    or {
                        k: v
                        for k, v in request.items()
                        if k not in {"turn_id", "message", "history"}
                    }
                    != stable
                    or not isinstance(request.get("message"), str)
                    or not 1 <= len(request["message"]) <= 16000
                ):
                    raise ValueError("Changed or expired activation.")
                token, current_account = credentials(args.auth_file)
                if current_account != account:
                    raise ValueError("Authentication account changed.")
                used.add(turn)
                result = asyncio.run(
                    run_turn(
                        service,
                        request,
                        partial(
                            provider_call,
                            client,
                            token=token,
                            account=account,
                            session_id=request["session_id"],
                        ),
                    )
                )
                result["timings"]["activation_seconds"] = time.perf_counter() - activated
                with (args.data_dir / "direct-metrics.jsonl").open("a", encoding="utf-8") as log:
                    log.write(
                        json.dumps(
                            {
                                "turn_id": turn,
                                "pid": os.getpid(),
                                "native_hermes_imported": any(
                                    name == "run_agent" or name.startswith("hermes_cli")
                                    for name in sys.modules
                                ),
                                **result["direct_metrics"],
                            }
                        )
                        + "\n"
                    )
                write_frame(result)
                expiry = time.perf_counter() + setup["standby_seconds"]
    except Exception as exc:
        code = str(exc) if isinstance(exc, ProviderFailure) else "direct_worker_failed"
        write_frame({"type": "error", "code": code, "exception": type(exc).__name__})


if __name__ == "__main__":
    main()
