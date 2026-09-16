"""Restricted Hermes construction, imported only in its separately pinned environment.

The conversation host must bind its MCP server to a fresh runtime turn before
calling this function. This module does not open a turn or implement reasoning.
"""

import inspect
import re
from functools import wraps

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
REASONING_EFFORTS = ("low",)


def install_call_authority():
    """Bind each Promethee RPC to its immutable native task ID, without replacing RPC.

    Qualified against Hermes 2179a279: registration calls this module's factory
    again after reconnects. Keep the private extension inside the owned worker;
    reject changed aliases/signatures rather than silently dropping the guard.
    """
    from tools import mcp_tool_handlers as handlers
    from tools import mcp_tool_registration as registration

    if getattr(registration, "_handlers", None) is not handlers:
        raise RuntimeError("Hermes MCP registration no longer uses the qualified handler module.")
    factory = getattr(handlers, "_make_tool_handler", None)
    installed = getattr(handlers, "_promethee_authority_factory", None)
    if installed is not None:
        if factory is not installed:
            raise RuntimeError("The Promethee call-authority factory was replaced.")
        return
    try:
        parameters = inspect.signature(factory).parameters
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Hermes MCP handler factory is unavailable.") from exc
    if tuple(parameters) != ("server_name", "tool_name", "tool_timeout") or any(
        parameter.kind != inspect.Parameter.POSITIONAL_OR_KEYWORD
        for parameter in parameters.values()
    ):
        raise RuntimeError("Hermes MCP handler factory has an unqualified signature.")

    @wraps(factory)
    def make_handler(server_name, tool_name, tool_timeout):
        native = factory(server_name, tool_name, tool_timeout)
        if server_name != "promethee":
            return native

        @wraps(native)
        def authorized(args, **kwargs):
            if not isinstance(args, dict) or "_promethee_turn_id" in args:
                raise ValueError(
                    "Tool arguments must not supply the reserved conversation authority."
                )
            turn_id = kwargs.get("task_id")
            if not isinstance(turn_id, str) or not re.fullmatch(r"turn-[a-f0-9]{32}", turn_id):
                raise ValueError("A current native conversation task ID is required.")
            return native({**args, "_promethee_turn_id": turn_id}, **kwargs)

        return authorized

    handlers._make_tool_handler = make_handler
    handlers._promethee_authority_factory = make_handler


def validate_chat_options(reasoning_effort=None, measure_timing=False):
    """Keep opt-in controls explicit; omission preserves the qualified defaults."""
    if reasoning_effort is not None and (
        not isinstance(reasoning_effort, str) or reasoning_effort not in REASONING_EFFORTS
    ):
        raise ValueError("Reasoning effort must be omitted or explicitly set to low.")
    if type(measure_timing) is not bool:
        raise ValueError("Timing measurement must be explicitly enabled or disabled.")


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
    *,
    model,
    api_key,
    base_url,
    api_mode,
    session_id,
    memory_enabled=False,
    provider="openai",
    reasoning_effort=None,
    call_authority=False,
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
    if type(call_authority) is not bool:
        raise ValueError("Call authority must be explicitly enabled or disabled.")
    validate_chat_options(reasoning_effort)
    expected = WORLD_TOOLS | MEMORY_TOOLS if memory_enabled else WORLD_TOOLS
    if call_authority:
        install_call_authority()
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
        **(
            {"reasoning_config": {"enabled": True, "effort": reasoning_effort}}
            if reasoning_effort is not None
            else {}
        ),
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


def refresh_resident_agent(
    agent, *, settings, provider, api_key, schemas, memory_enabled=False, call_authority=False
):
    """Verify the resident identity and refresh its native MCP tool snapshot.

    Fixed-turn callers close and rebind their transport first. With per-call
    authority the connection remains open and its handler guard is revalidated.
    Neither path opens a reasoning turn here.
    """
    if type(call_authority) is not bool:
        raise ValueError("Call authority must be explicitly enabled or disabled.")
    if call_authority:
        install_call_authority()
    from tools.mcp_tool import discover_mcp_tools
    from tools.mcp_tool_agent import refresh_agent_mcp_tools

    expected = WORLD_TOOLS | MEMORY_TOOLS if memory_enabled else WORLD_TOOLS
    if set(discover_mcp_tools()) != expected:
        raise RuntimeError("Resident MCP discovery changed the qualified tool scope.")
    refresh_agent_mcp_tools(
        agent,
        enabled_override=["mcp-promethee"],
        quiet_mode=True,
        content_aware=True,
        preserve_prefix=False,
    )
    if (
        set(agent.valid_tool_names) != expected
        or agent.tools != schemas
        or agent._fallback_chain
        or agent.provider != provider
        or agent.model != settings["model"]
        or agent.api_mode != settings["api_mode"]
        or agent.base_url != settings["base_url"]
        or agent.api_key != api_key
        or agent.session_id != settings["session_id"]
    ):
        raise RuntimeError("Resident agent identity, transport or schemas changed.")
