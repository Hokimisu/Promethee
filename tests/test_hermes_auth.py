"""Provider selection must not redirect ChatGPT credentials or change the agent loop."""

import sys
from types import SimpleNamespace

import pytest

from promethee.hermes_adapter import (
    CODEX_BASE_URL,
    WORLD_TOOLS,
    create_agent,
    resolve_hermes_codex_credentials,
)


def resolver(monkeypatch, credentials):
    calls = []

    def resolve(**kwargs):
        calls.append(kwargs)
        return credentials

    monkeypatch.setitem(
        sys.modules,
        "hermes_cli.runtime_provider",
        SimpleNamespace(resolve_runtime_provider=resolve),
    )
    return calls


def test_native_auth_uses_explicit_model_and_provider(monkeypatch):
    credentials = {
        "provider": "openai-codex",
        "api_mode": "codex_responses",
        "base_url": CODEX_BASE_URL,
        "api_key": "fixture-credential",
    }
    calls = resolver(monkeypatch, credentials)
    assert (
        resolve_hermes_codex_credentials(
            model="gpt-6-astra", base_url=CODEX_BASE_URL, api_mode="codex_responses"
        )
        is credentials
    )
    assert calls == [{"requested": "openai-codex", "target_model": "gpt-6-astra"}]


@pytest.mark.parametrize(
    "endpoint,mode",
    [
        ("http://127.0.0.1:9999", "codex_responses"),
        ("https://chatgpt.com.example.invalid/backend-api/codex", "codex_responses"),
        (CODEX_BASE_URL, "chat_completions"),
        (CODEX_BASE_URL, "codex_app_server"),
    ],
)
def test_auth_rejects_other_endpoints_before_resolving(monkeypatch, endpoint, mode):
    calls = resolver(monkeypatch, {})
    with pytest.raises(ValueError):
        resolve_hermes_codex_credentials(model="gpt-6-astra", base_url=endpoint, api_mode=mode)
    assert not calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", "openrouter"),
        ("api_mode", "codex_app_server"),
        ("base_url", "https://example.invalid"),
        ("api_key", ""),
        ("api_key", None),
    ],
)
def test_resolved_auth_cannot_fall_back(monkeypatch, field, value):
    credentials = {
        "provider": "openai-codex",
        "api_mode": "codex_responses",
        "base_url": CODEX_BASE_URL,
        "api_key": "fixture-credential",
        field: value,
    }
    resolver(monkeypatch, credentials)
    with pytest.raises(ValueError):
        resolve_hermes_codex_credentials(
            model="gpt-6-astra", base_url=CODEX_BASE_URL, api_mode="codex_responses"
        )


@pytest.mark.parametrize(
    "changed",
    [
        {},
        {"provider": "openai"},
        {"model": "different-model"},
        {"api_mode": "codex_app_server"},
        {"valid_tool_names": WORLD_TOOLS | {"terminal"}},
    ],
)
def test_constructed_agent_must_preserve_native_scope(monkeypatch, changed):
    def factory(**kwargs):
        state = {
            "provider": kwargs["provider"],
            "model": kwargs["model"],
            "api_mode": kwargs["api_mode"],
            "valid_tool_names": WORLD_TOOLS,
            "_fallback_chain": [],
            **changed,
        }
        return SimpleNamespace(**state)

    monkeypatch.setitem(sys.modules, "run_agent", SimpleNamespace(AIAgent=factory))
    monkeypatch.setitem(
        sys.modules, "tools.mcp_tool", SimpleNamespace(discover_mcp_tools=lambda: WORLD_TOOLS)
    )
    arguments = dict(
        model="gpt-6-astra",
        api_key="fixture-credential",
        base_url=CODEX_BASE_URL,
        api_mode="codex_responses",
        provider="openai-codex",
        session_id="qualification",
    )
    if changed:
        with pytest.raises(RuntimeError):
            create_agent(**arguments)
    else:
        assert create_agent(**arguments).api_mode == "codex_responses"


@pytest.mark.parametrize("effort", [None, "low"])
def test_reasoning_option_reaches_native_constructor_exactly(monkeypatch, effort):
    calls = []

    def factory(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            provider=kwargs["provider"],
            model=kwargs["model"],
            api_mode=kwargs["api_mode"],
            valid_tool_names=WORLD_TOOLS,
            _fallback_chain=[],
        )

    monkeypatch.setitem(sys.modules, "run_agent", SimpleNamespace(AIAgent=factory))
    monkeypatch.setitem(
        sys.modules, "tools.mcp_tool", SimpleNamespace(discover_mcp_tools=lambda: WORLD_TOOLS)
    )
    create_agent(
        model="gpt-6-astra",
        api_key="fixture-credential",
        base_url=CODEX_BASE_URL,
        api_mode="codex_responses",
        provider="openai-codex",
        session_id="fixture",
        reasoning_effort=effort,
    )
    if effort is None:
        assert "reasoning_config" not in calls[0]
    else:
        assert calls[0]["reasoning_config"] == {"enabled": True, "effort": "low"}


@pytest.mark.parametrize("effort", ["", "LOW", "none", "medium", False, 1, [], {"effort": "low"}])
def test_malformed_reasoning_rejected_before_native_import(monkeypatch, effort):
    monkeypatch.setitem(sys.modules, "run_agent", None)
    with pytest.raises(ValueError, match="Reasoning effort"):
        create_agent(
            model="gpt-6-astra",
            api_key="fixture-credential",
            base_url=CODEX_BASE_URL,
            api_mode="codex_responses",
            provider="openai-codex",
            session_id="fixture",
            reasoning_effort=effort,
        )
