"""The worker's input boundary remains testable without installing Hermes."""

import json
import os
import subprocess
import sys
from pathlib import Path

from promethee.hermes_worker import redact


def call(tmp_path, payload, *, key=None):
    environment = dict(os.environ)
    environment.pop("PROMETHEE_OPENAI_API_KEY", None)
    if key:
        environment["PROMETHEE_OPENAI_API_KEY"] = key
    script = Path(__file__).resolve().parents[1] / "src/promethee/hermes_worker.py"
    result = subprocess.run(
        [sys.executable, str(script), "--hermes-root", str(tmp_path), "--profile", str(tmp_path)],
        input=payload + "\n",
        text=True,
        capture_output=True,
        env=environment,
        timeout=10,
    )
    assert result.returncode == 0
    if key:
        assert key not in result.stdout + result.stderr
    return json.loads(result.stdout)


def test_missing_credentials_fail_before_loading_hermes(tmp_path):
    assert call(tmp_path, "{}") == {"type": "error", "code": "credentials_missing"}


def test_malformed_input_is_an_error_without_echoing_it(tmp_path):
    result = call(tmp_path, '{"private": "unfinished', key="diagnostic-secret-key")
    assert result["type"] == "error" and result["code"] == "conversation_failed"
    assert "private" not in json.dumps(result)


def test_worker_refuses_a_profile_bound_to_another_turn(tmp_path):
    (tmp_path / "config.yaml").write_text(
        json.dumps({"mcp_servers": {"promethee": {"args": ["--turn-id", "turn-other"]}}})
    )
    request = {
        "turn_id": "turn-current",
        "message": "hello",
        "history": [],
        "model": "test",
        "base_url": "http://127.0.0.1:1",
        "api_mode": "chat_completions",
        "session_id": "test",
    }
    result = call(tmp_path, json.dumps(request), key="diagnostic-secret-key")
    assert result["type"] == "error" and result["exception"] == "ValueError"


def test_redaction_preserves_json_structure():
    value = {"type": "type secret", "messages": [{"content": "secret"}]}
    assert redact(value, "secret") == {
        "type": "type [credential redacted]",
        "messages": [{"content": "[credential redacted]"}],
    }
    assert value["messages"][0]["content"] == "secret"
