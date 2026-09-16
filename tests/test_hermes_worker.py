"""The worker's input boundary remains testable without installing Hermes."""

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

from promethee.chat import prepare_profile
from promethee.hermes_adapter import CODEX_BASE_URL, WORLD_TOOLS
from promethee.hermes_worker import redact


def call(tmp_path, payload, *, key=None, hermes_root=None, auth="api-key"):
    environment = dict(os.environ)
    environment.pop("PROMETHEE_OPENAI_API_KEY", None)
    if key:
        environment["PROMETHEE_OPENAI_API_KEY"] = key
    script = Path(__file__).resolve().parents[1] / "src/promethee/hermes_worker.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--hermes-root",
            str(hermes_root or tmp_path),
            "--profile",
            str(tmp_path),
            "--auth",
            auth,
        ],
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


def test_nonresident_worker_cannot_use_per_call_authority(tmp_path):
    prepare_profile(tmp_path / "profile", tmp_path, "turn-unused", call_authority=True)
    result = call(
        tmp_path / "profile",
        json.dumps(fixture_request()),
        key="diagnostic-secret-key",
    )
    assert result == {"type": "error", "code": "conversation_failed", "exception": "ValueError"}


@pytest.mark.parametrize("memory", [False, True])
def test_per_call_profile_preserves_scope_and_has_no_mutable_turn(tmp_path, memory):
    profile = tmp_path / "profile"
    vault = tmp_path / "memory" if memory else None
    prepare_profile(profile, tmp_path, "turn-unused", vault=vault, call_authority=True)
    server = json.loads((profile / "config.yaml").read_text())["mcp_servers"]["promethee"]
    assert server["args"][-1] == "--call-authority"
    assert "--turn-id" not in server["args"] and "turn-unused" not in server["args"]
    assert ("--vault" in server["args"]) == memory
    assert len(server["tools"]["include"]) == (9 if memory else 5)


def test_redaction_preserves_json_structure():
    value = {"type": "type secret", "messages": [{"content": "secret"}]}
    assert redact(value, "secret") == {
        "type": "type [credential redacted]",
        "messages": [{"content": "[credential redacted]"}],
    }
    assert value["messages"][0]["content"] == "secret"


def fixture_request(**options):
    return {
        "turn_id": "turn-current",
        "message": "A neutral fixture",
        "history": [],
        "model": "gpt-6-astra",
        "base_url": CODEX_BASE_URL,
        "api_mode": "codex_responses",
        "session_id": "session-fixture",
        **options,
    }


def fake_hermes(tmp_path):
    root = tmp_path / "hermes"
    root.mkdir()
    (root / "run_agent.py").write_text(
        "import json\nfrom pathlib import Path\n"
        "class AIAgent:\n"
        " def __init__(self, **kw):\n"
        "  self.model=kw['model']; self.provider=kw['provider']; self.api_mode=kw['api_mode']\n"
        f"  self.valid_tool_names={sorted(WORLD_TOOLS)!r}; self._fallback_chain=[]\n"
        "  Path(__file__).with_name('options.json').write_text(json.dumps(\n"
        "   {k: v for k, v in kw.items() if k == 'reasoning_config'}))\n"
        " def run_conversation(self, message, conversation_history, task_id):\n"
        "  if message == 'explode': raise RuntimeError('diagnostic-secret-key')\n"
        "  return {'final_response':'Fixture response', 'messages': [\n"
        "   *conversation_history, {'role':'user','content':message},\n"
        "   {'role':'assistant','content':'Fixture response'}]}\n"
    )
    (root / "tools").mkdir()
    (root / "tools/__init__.py").write_text("")
    (root / "tools/mcp_tool.py").write_text(
        "from pathlib import Path\n"
        f"def discover_mcp_tools(): return {sorted(WORLD_TOOLS)!r}\n"
        "def shutdown_mcp_servers(): Path(__file__).with_name('closed').touch()\n"
    )
    (root / "hermes_cli").mkdir()
    (root / "hermes_cli/__init__.py").write_text("")
    (root / "hermes_cli/runtime_provider.py").write_text(
        "def resolve_runtime_provider(**kw):\n"
        " assert kw == {'requested':'openai-codex','target_model':'gpt-6-astra'}\n"
        f" return {{'provider':'openai-codex','api_mode':'codex_responses',"
        f"'base_url':{CODEX_BASE_URL!r},'api_key':'diagnostic-secret-key'}}\n"
    )
    profile = tmp_path / "profiles/fixture"
    prepare_profile(profile, tmp_path, "turn-current")
    return root, profile


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"reasoning_effort": None, "measure_timing": False},
        {"reasoning_effort": "low", "measure_timing": True},
    ],
)
@pytest.mark.parametrize("auth", ["api-key", "hermes-codex"])
def test_native_worker_options_and_opt_in_measurements(tmp_path, options, auth):
    root, profile = fake_hermes(tmp_path)
    response = call(
        profile,
        json.dumps(fixture_request(**options)),
        key="diagnostic-secret-key",
        hermes_root=root,
        auth=auth,
    )
    assert response["type"] == "result"
    assert response["text"] == "Fixture response"
    assert (root / "tools/closed").exists()
    expected = (
        {"reasoning_config": {"enabled": True, "effort": "low"}}
        if options.get("reasoning_effort")
        else {}
    )
    assert json.loads((root / "options.json").read_text()) == expected
    if options.get("measure_timing"):
        measured = response["timings"]
        assert set(measured) == {
            "import_seconds",
            "auth_seconds",
            "agent_construct_seconds",
            "run_conversation_seconds",
            "mcp_shutdown_seconds",
            "worker_total_seconds",
        }
        assert all(
            type(value) is float and math.isfinite(value) and value >= 0
            for value in measured.values()
        )
        assert measured["worker_total_seconds"] >= sum(
            v for k, v in measured.items() if k != "worker_total_seconds"
        )
    else:
        assert "timings" not in response


def test_error_keeps_elapsed_phases_and_shutdown_without_exception_text(tmp_path):
    root, profile = fake_hermes(tmp_path)
    response = call(
        profile,
        json.dumps(fixture_request(measure_timing=True, message="explode")),
        key="diagnostic-secret-key",
        hermes_root=root,
    )
    assert response["type"] == "error" and response["exception"] == "RuntimeError"
    assert (root / "tools/closed").exists()
    assert response["timings"]["run_conversation_seconds"] >= 0
    assert response["timings"]["mcp_shutdown_seconds"] >= 0
    assert "diagnostic-secret-key" not in json.dumps(response)


@pytest.mark.parametrize(
    "options",
    [
        {"reasoning_effort": []},
        {"reasoning_effort": "high"},
        {"measure_timing": "true"},
        {"measure_timing": 1},
        {"measure_timing": None},
        {"reasoning_config": {"effort": "low"}},
    ],
)
def test_invalid_options_fail_before_loading_profile_or_hermes(tmp_path, options):
    response = call(tmp_path, json.dumps(fixture_request(**options)), key="diagnostic-secret-key")
    assert response == {"type": "error", "code": "conversation_failed", "exception": "ValueError"}
