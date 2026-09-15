"""One native Hermes conversation call in its isolated Python environment.

stdin/stdout carry one bounded JSON request/result. The trusted host owns turn
creation, profile selection, deadlines, cancellation and history persistence.
"""

import argparse
import contextlib
import json
import os
import sys
from pathlib import Path


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-root", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--auth", choices=["api-key", "hermes-codex"], default="api-key")
    args = parser.parse_args()
    profile = args.profile.resolve()
    hermes_root = args.hermes_root.resolve()
    protocol = sys.stdout
    key = os.environ.get("PROMETHEE_OPENAI_API_KEY")
    if not key and args.auth == "api-key":
        protocol.write(json.dumps({"type": "error", "code": "credentials_missing"}) + "\n")
        return
    try:
        line = sys.stdin.readline(1_048_577)
        if len(line) > 1_048_576 or not line.endswith("\n"):
            raise ValueError("Oversized or incomplete conversation request.")
        request = json.loads(line)
        if set(request) != {
            "turn_id",
            "message",
            "history",
            "model",
            "base_url",
            "api_mode",
            "session_id",
        }:
            raise ValueError("Unexpected conversation request fields.")
        if not isinstance(request["message"], str) or not 1 <= len(request["message"]) <= 16000:
            raise ValueError("Expected a nonempty message of at most 16000 characters.")
        if not isinstance(request["history"], list):
            raise ValueError("Expected native Hermes conversation history.")
        # Profile JSON is also valid YAML; this worker accepts only the exact
        # host-generated shape, never a personal Hermes config or its secrets.
        config = json.loads((profile / "config.yaml").read_text(encoding="utf-8"))
        params = config["mcp_servers"]["promethee"]["args"]
        if params[-2:] != ["--turn-id", request["turn_id"]]:
            raise ValueError("The MCP profile is not bound to this conversation turn.")
        os.environ["HERMES_HOME"] = str(profile)
        os.chdir(profile)
        sys.path.insert(0, str(hermes_root))
        provider = "openai"
        if args.auth == "hermes-codex":
            # The native profile path inherits authentication through Hermes,
            # while config, context and memory remain in this fresh profile.
            if profile.parent.name != "profiles":
                raise ValueError("Hermes authentication requires a native dedicated profile.")
            with contextlib.redirect_stdout(sys.stderr):
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
            from hermes_adapter import create_agent
            from tools.mcp_tool import shutdown_mcp_servers

            try:
                agent = create_agent(
                    model=request["model"],
                    api_key=key,
                    base_url=request["base_url"],
                    api_mode=request["api_mode"],
                    session_id=request["session_id"],
                    memory_enabled="--vault" in params,
                    provider=provider,
                )
                result = agent.run_conversation(
                    request["message"],
                    conversation_history=request["history"],
                    task_id=request["turn_id"],
                )
            finally:
                shutdown_mcp_servers()
        if not isinstance(result, dict) or not isinstance(result.get("messages"), list):
            raise ValueError("Hermes returned an unexpected conversation result.")
        response = {
            "type": "result",
            "turn_id": request["turn_id"],
            "messages": result.get("messages", []),
            "text": result.get("final_response"),
            "interrupted": bool(result.get("interrupted")),
            "failed": bool(result.get("error")),
        }
        encoded = json.dumps(redact(response, key), ensure_ascii=False, allow_nan=False)
        if len(encoded) > 4_194_304:
            raise ValueError("Oversized conversation result.")
        protocol.write(encoded + "\n")
    except Exception as exc:
        # Provider exceptions can quote credentials. Never return their raw text.
        protocol.write(
            json.dumps(
                {"type": "error", "code": "conversation_failed", "exception": type(exc).__name__}
            )
            + "\n"
        )
    protocol.flush()


if __name__ == "__main__":
    main()
