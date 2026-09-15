"""Restricted Hermes construction, imported only in its separately pinned environment.

The conversation host must bind its MCP server to a fresh runtime turn before
calling this function. This module does not open a turn or implement reasoning.
"""

WORLD_TOOLS = frozenset(
    "mcp__promethee__" + name
    for name in (
        "read_world",
        "list_capabilities",
        "submit_action",
        "read_execution",
        "cancel_action",
    )
)
MEMORY_TOOLS = frozenset(
    "mcp__promethee__" + name
    for name in ("search_memory", "read_memory_note", "read_memory_source", "write_memory_note")
)


CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"


def resolve_hermes_codex_credentials(*, model, base_url, api_mode):
    """Use Hermes' existing profile authentication; never export credentials."""
    if base_url != CODEX_BASE_URL or api_mode != "codex_responses":
        raise ValueError("Hermes ChatGPT authentication requires its official Codex endpoint.")
    from hermes_cli.runtime_provider import resolve_runtime_provider

    credentials = resolve_runtime_provider(requested="openai-codex", target_model=model)
    if (
        credentials.get("provider") != "openai-codex"
        or credentials.get("api_mode") != api_mode
        or credentials.get("base_url") != base_url
        or not isinstance(credentials.get("api_key"), str)
        or not credentials["api_key"].strip()
    ):
        raise ValueError("Hermes resolved a different provider or an unavailable credential.")
    return credentials


def create_agent(
    *, model, api_key, base_url, api_mode, session_id, memory_enabled=False, provider="openai"
):
    """Use the installed Hermes loop, with no project context or fallback model.

    HERMES_HOME and cwd must already identify the dedicated profile before any
    Hermes import. Its configuration disables tool_search assembly and includes
    only world tools and, when explicitly enabled, the four sourced memory tools.
    Callers retain ownership of transport cleanup.
    """
    if not all(
        isinstance(value, str) and value.strip() for value in (model, api_key, base_url, session_id)
    ):
        raise ValueError("Explicit provider credentials, model, endpoint and session are required.")
    if api_mode not in {"chat_completions", "codex_responses"}:
        raise ValueError("Use an explicitly verified Hermes API mode.")
    if provider not in {"openai", "openai-codex"}:
        raise ValueError("Use an explicitly supported Hermes provider.")
    if provider == "openai-codex" and (base_url != CODEX_BASE_URL or api_mode != "codex_responses"):
        raise ValueError("Hermes ChatGPT authentication requires its official Codex endpoint.")
    if type(memory_enabled) is not bool:
        raise ValueError("Memory scope must be explicitly enabled or disabled.")
    expected = WORLD_TOOLS | MEMORY_TOOLS if memory_enabled else WORLD_TOOLS
    from run_agent import AIAgent
    from tools.mcp_tool import discover_mcp_tools

    discovered = set(discover_mcp_tools())
    if discovered != expected:
        raise RuntimeError("The dedicated profile differs from its explicit Promethee tool scope.")
    agent = AIAgent(
        model=model,
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        api_mode=api_mode,
        session_id=session_id,
        enabled_toolsets=["mcp-promethee"],
        max_iterations=8,
        quiet_mode=True,
        skip_context_files=True,
        load_soul_identity=False,
        skip_memory=True,
        skip_background_review=True,
        fallback_model=None,
        checkpoints_enabled=False,
    )
    if (
        set(agent.valid_tool_names) != expected
        or agent._fallback_chain
        or agent.provider != provider
        or agent.model != model
        or agent.api_mode != api_mode
    ):
        raise RuntimeError(
            "Hermes scope differs from the qualified tool and provider configuration."
        )
    return agent
