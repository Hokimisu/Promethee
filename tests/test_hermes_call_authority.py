"""Per-call authority wraps the native RPC; no model, socket or GPU is needed."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import ModuleType, SimpleNamespace

import pytest

from promethee.hermes_adapter import (
    CODEX_BASE_URL,
    WORLD_TOOLS,
    create_agent,
    install_call_authority,
    refresh_resident_agent,
)

FIRST = "turn-" + "a" * 32
SECOND = "turn-" + "b" * 32


@pytest.fixture
def native(monkeypatch):
    calls, constructed = [], []

    def factory(server_name, tool_name, tool_timeout):
        def handler(args, **kwargs):
            calls.append((args, kwargs))
            return "native-result"

        constructed.append((server_name, tool_name, tool_timeout, handler))
        return handler

    handlers = ModuleType("tools.mcp_tool_handlers")
    handlers._make_tool_handler = factory
    registration = ModuleType("tools.mcp_tool_registration")
    registration._handlers = handlers
    tools = ModuleType("tools")
    tools.mcp_tool_handlers = handlers
    tools.mcp_tool_registration = registration
    for module in (tools, handlers, registration):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    return SimpleNamespace(
        handlers=handlers,
        registration=registration,
        factory=factory,
        calls=calls,
        constructed=constructed,
    )


def test_registration_factory_is_wrapped_once_and_reused_after_reconnect(native):
    install_call_authority()
    installed = native.handlers._make_tool_handler
    install_call_authority()
    assert native.handlers._make_tool_handler is installed
    args = {"action": {"kind": "posture", "args": {"name": "standing"}}}
    for turn in (FIRST, SECOND):
        handler = native.registration._handlers._make_tool_handler("promethee", "submit_action", 10)
        assert handler(args, task_id=turn, session_id="world", user_task=None) == "native-result"
    assert "_promethee_turn_id" not in args
    for (bound, kwargs), turn in zip(native.calls, (FIRST, SECOND), strict=True):
        assert bound is not args and bound["action"] is args["action"]
        assert bound == {**args, "_promethee_turn_id": turn}
        assert kwargs == {"task_id": turn, "session_id": "world", "user_task": None}


def test_other_servers_keep_the_exact_native_handler(native):
    install_call_authority()
    handler = native.handlers._make_tool_handler("other", "read_world", 12)
    assert handler is native.constructed[-1][-1]
    args = {"_promethee_turn_id": "not-our-authority"}
    assert handler(args) == "native-result"
    assert native.calls == [(args, {})]


@pytest.mark.parametrize(
    "task_id",
    [
        None,
        "",
        1,
        False,
        [],
        FIRST + "\n",
        "turn-" + "A" * 32,
        "turn-" + "a" * 31,
        "world-" + "a" * 32,
    ],
)
def test_missing_or_malformed_identity_never_reaches_native_rpc(native, task_id):
    install_call_authority()
    handler = native.handlers._make_tool_handler("promethee", "submit_action", 10)
    with pytest.raises(ValueError, match="task ID"):
        handler({}, **({} if task_id is None else {"task_id": task_id}))
    assert native.calls == []


@pytest.mark.parametrize(
    "args", [None, [], {"_promethee_turn_id": None}, {"_promethee_turn_id": FIRST}]
)
def test_spoofed_authority_is_refused_even_if_equal_to_real_turn(native, args):
    install_call_authority()
    handler = native.handlers._make_tool_handler("promethee", "submit_action", 10)
    with pytest.raises(ValueError, match="reserved"):
        handler(args, task_id=FIRST)
    assert native.calls == []


def test_delayed_old_call_does_not_adopt_new_call_authority(native):
    entered, release = Event(), Event()
    seen = []

    def factory(server_name, tool_name, tool_timeout):
        def handler(args, **kwargs):
            if args["label"] == "old":
                entered.set()
                assert release.wait(5)
            seen.append((args["label"], args["_promethee_turn_id"]))
            return args["_promethee_turn_id"]

        return handler

    native.handlers._make_tool_handler = factory
    install_call_authority()
    handler = native.handlers._make_tool_handler("promethee", "submit_action", 10)
    with ThreadPoolExecutor(max_workers=1) as pool:
        old = pool.submit(handler, {"label": "old"}, task_id=FIRST)
        try:
            assert entered.wait(5)
            assert handler({"label": "new"}, task_id=SECOND) == SECOND
        finally:
            release.set()
        assert old.result(timeout=5) == FIRST
    assert seen == [("new", SECOND), ("old", FIRST)]


def test_changed_registration_alias_and_factory_fail_closed(native):
    native.registration._handlers = SimpleNamespace()
    with pytest.raises(RuntimeError, match="registration"):
        install_call_authority()
    assert native.handlers._make_tool_handler is native.factory
    native.registration._handlers = native.handlers
    install_call_authority()
    native.handlers._make_tool_handler = native.factory
    with pytest.raises(RuntimeError, match="replaced"):
        install_call_authority()


@pytest.mark.parametrize("factory", [None, lambda *args: None])
def test_missing_or_changed_factory_signature_fails_closed(native, factory):
    native.handlers._make_tool_handler = factory
    with pytest.raises(RuntimeError, match="factory"):
        install_call_authority()


def fake_agent(monkeypatch, native, *, expected_authority):
    def discover():
        installed = native.handlers._make_tool_handler is not native.factory
        assert installed is expected_authority
        return WORLD_TOOLS

    def construct(**kwargs):
        return SimpleNamespace(**kwargs, valid_tool_names=WORLD_TOOLS, tools=[], _fallback_chain=[])

    monkeypatch.setitem(sys.modules, "run_agent", SimpleNamespace(AIAgent=construct))
    monkeypatch.setitem(sys.modules, "tools.mcp_tool", SimpleNamespace(discover_mcp_tools=discover))
    monkeypatch.setitem(
        sys.modules,
        "tools.mcp_tool_agent",
        SimpleNamespace(refresh_agent_mcp_tools=lambda *a, **k: None),
    )
    return dict(
        model="fixture",
        api_key="fixture",
        base_url=CODEX_BASE_URL,
        api_mode="codex_responses",
        session_id="fixture",
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_opt_in_installation_precedes_discovery_and_refresh(monkeypatch, native, enabled):
    settings = fake_agent(monkeypatch, native, expected_authority=enabled)
    agent = create_agent(**settings, **({"call_authority": True} if enabled else {}))
    refresh_resident_agent(
        agent,
        settings=settings,
        provider="openai",
        api_key="fixture",
        schemas=[],
        call_authority=enabled,
    )
    if enabled:
        native.handlers._make_tool_handler = native.factory
        with pytest.raises(RuntimeError, match="replaced"):
            refresh_resident_agent(
                agent,
                settings=settings,
                provider="openai",
                api_key="fixture",
                schemas=[],
                call_authority=True,
            )


@pytest.mark.parametrize("flag", [None, 0, 1, "true", []])
def test_malformed_opt_in_is_rejected_before_native_import(monkeypatch, flag):
    monkeypatch.setitem(sys.modules, "run_agent", None)
    with pytest.raises(ValueError, match="Call authority"):
        create_agent(
            model="fixture",
            api_key="fixture",
            base_url=CODEX_BASE_URL,
            api_mode="codex_responses",
            session_id="fixture",
            call_authority=flag,
        )


def test_optional_real_registration_factory_preserves_native_handler(tmp_path):
    checkout = Path(
        os.environ.get(
            "PROMETHEE_TEST_HERMES_ROOT",
            Path(__file__).resolve().parents[1] / ".local/hermes-agent",
        )
    )
    if not (checkout / "tools/mcp_tool_handlers.py").is_file():
        pytest.skip("Optional native Hermes checkout is not installed.")
    code = r"""
import asyncio,json,sys
from types import SimpleNamespace
from unittest.mock import patch
from promethee.hermes_adapter import install_call_authority
sys.path.insert(0,sys.argv[1])
from tools import mcp_tool_handlers as handlers, mcp_tool_registration as registration
from tools.registry import registry
assert registration._handlers is handlers
install_call_authority()
seen=[]
class Session:
    async def call_tool(self,name,arguments):
        seen.append((name,arguments))
        return SimpleNamespace(content=[SimpleNamespace(type='text',text='native-result')])
server=SimpleNamespace(session=Session(),_rpc_lock=asyncio.Lock())
tool=SimpleNamespace(name='read_world',description='fixture',input_schema={'type':'object'},annotations=None)
def dispatch(server_name,server,op,call,*args,**kwargs):
    return asyncio.run(call())
with patch.object(handlers,'_trust_gate_check',return_value=None), \
     patch.object(handlers,'_check_circuit_breaker',return_value=None), \
     patch.object(handlers,'_acquire_call_server',return_value=(server,None)), \
     patch.object(handlers,'_dispatch',side_effect=dispatch):
    for letter in ('a','b'):
        candidates=registration._tool_candidates('promethee',[tool],lambda name:True,10)
        assert '_promethee_turn_id' not in json.dumps(candidates[0].schema)
        names=registration._register_candidates(
            'promethee',candidates,check_fn=lambda:True,scope=lambda:None,lazy=False)
        assert names==['mcp__promethee__read_world']
        result=registry.dispatch(names[0],{},task_id='turn-'+letter*32,session_id='world')
        assert 'native-result' in result
        before=len(seen)
        for args,kwargs in (({},{}),({'_promethee_turn_id':'spoof-must-not-echo'},
                                    {'task_id':'turn-'+letter*32})):
            refused=registry.dispatch(names[0],args,**kwargs)
            assert 'error' in json.loads(refused) if isinstance(refused,str) else 'error' in refused
            assert 'spoof-must-not-echo' not in str(refused)
            assert len(seen)==before
print(json.dumps(seen))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, str(checkout.resolve())],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
        timeout=20,
        env={**os.environ, "HERMES_HOME": str(tmp_path / "native-profile")},
    )
    assert json.loads(completed.stdout) == [
        ["read_world", {"_promethee_turn_id": FIRST}],
        ["read_world", {"_promethee_turn_id": SECOND}],
    ]
