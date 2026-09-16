"""Resident transport tests: deterministic agent, real isolated MCP subprocesses."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_chat_host import alive
from test_chat_prewarm import until

from promethee.chat import ResidentProcess, open_text_host
from promethee.execution import ExecutionService
from promethee.hermes_adapter import CODEX_BASE_URL
from promethee.runtime import Runtime

MCP_FIXTURE = r"""
import json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).parent.parent
proc=None
definitions=[]
counter=0
bound=None
def log(event,**data):
 with (ROOT/'events.jsonl').open('a',encoding='utf-8') as f:
  f.write(json.dumps({'event':event,**data})+'\n')
def rpc(method,params=None):
 global counter
 counter+=1
 frame={'jsonrpc':'2.0','id':counter,'method':method}
 if params is not None: frame['params']=params
 proc.stdin.write(json.dumps(frame)+'\n');proc.stdin.flush()
 while True:
  line=proc.stdout.readline()
  if not line: raise RuntimeError('MCP fixture connection closed')
  reply=json.loads(line)
  if reply.get('id')==counter:
   if 'error' in reply: raise RuntimeError('MCP protocol rejected fixture')
   return reply['result']
def discover_mcp_tools():
 global proc,definitions,bound
 if proc is None:
  cfg=json.loads((Path(os.environ['HERMES_HOME'])/'config.yaml').read_text())['mcp_servers']['promethee']
  bound=cfg['args'][-1]
  proc=subprocess.Popen([cfg['command'],*cfg['args']],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
   stderr=subprocess.DEVNULL,text=True,encoding='utf-8')
  rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},
   'clientInfo':{'name':'resident-cpu-fixture','version':'1'}})
  proc.stdin.write(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'})+'\n');proc.stdin.flush()
  definitions=rpc('tools/list')['tools']
  log('connect',turn_id=bound,pid=proc.pid)
 return ['mcp__promethee__'+item['name'] for item in definitions]
def schemas():
 result=[{'type':'function','function':{'name':'mcp__promethee__'+item['name'],
  'description':item.get('description',''),'parameters':item['inputSchema']}}
  for item in definitions]
 if (ROOT/'change-schema').exists():result[0]['function']['description']='Unexpected change'
 return result
def get_mcp_status():
 connected=proc is not None and proc.poll() is None
 return [{'name':'promethee','connected':connected,
  'status':'connected' if connected else 'configured'}]
def shutdown_mcp_servers(*,names=None):
 global proc,definitions
 if proc is not None:
  pid=proc.pid
  proc.stdin.close();proc.wait(timeout=5);proc.stdout.close()
  log('shutdown',turn_id=bound,pid=pid,returncode=proc.returncode)
  proc=None;definitions=[]
def call(name,args=None,*,task_id):
 from tools import mcp_tool_handlers
 return mcp_tool_handlers._make_tool_handler('promethee',name,10)(args or {},task_id=task_id)

def dispatch(name,args):
 result=rpc('tools/call',{'name':name,'arguments':args or {}})
 log('tool',name=name,turn_id=args.get('_promethee_turn_id'),is_error=result.get('isError',False))
 if result.get('isError'):raise RuntimeError('Actual world tool rejected fixture')
 return result.get('structuredContent') or json.loads(result['content'][0]['text'])
"""

AGENT_FIXTURE = """
import json,subprocess,sys,time
from pathlib import Path
from tools import mcp_tool
ROOT=Path(__file__).parent
class AIAgent:
 def __init__(self,**kw):
  for name in ('model','provider','api_mode','base_url','api_key','session_id'):
   setattr(self,name,kw[name])
  self.tools=mcp_tool.schemas();self.valid_tool_names=set(mcp_tool.discover_mcp_tools());self._fallback_chain=[]
  mcp_tool.log('construct',session=self.session_id)
 def run_conversation(self,message,conversation_history,task_id,system_message=None):
  mcp_tool.log('model',turn_id=task_id,message=message,history=conversation_history,system_message=system_message)
  if message=='wait':
   child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
   (ROOT/'wait-child.pid').write_text(str(child.pid));time.sleep(60)
  if message.startswith('submit'):
   world=mcp_tool.call('read_world',task_id=task_id)
   action=mcp_tool.call('submit_action',{'request_id':'resident-'+task_id[-12:],
    'expected_revision':world['revision'],'action':{'kind':'move','args':{'position':[0.1,0.0]}}},task_id=task_id)
   mcp_tool.log('accepted',turn_id=task_id,request_id=action['request_id'],status=action['status'])
  messages=[*conversation_history,{'role':'user','content':message},{'role':'assistant','content':'Fixture'}]
  if message=='bad-history':messages=[messages[-1]]
  return {'final_response':'Fixture','messages':messages,'error':message=='fail',
   'failed':message=='native-failed','partial':message=='native-partial',
   'completed':message!='native-incomplete'}
 def close(self):mcp_tool.log('agent_close')
"""


@pytest.fixture
def resident_args(tmp_path):
    pytest.importorskip("mcp")
    root = tmp_path / "fake-hermes"
    root.mkdir()
    (root / "run_agent.py").write_text(AGENT_FIXTURE, encoding="utf-8")
    (root / "tools").mkdir()
    (root / "tools/__init__.py").write_text("")
    (root / "tools/mcp_tool.py").write_text(MCP_FIXTURE, encoding="utf-8")
    (root / "tools/mcp_tool_handlers.py").write_text(
        "from tools import mcp_tool\n"
        "def _make_tool_handler(server_name,tool_name,tool_timeout):\n"
        " def handler(args,**kw):return mcp_tool.dispatch(tool_name,args)\n"
        " return handler\n"
    )
    (root / "tools/mcp_tool_registration.py").write_text(
        "from tools import mcp_tool_handlers as _handlers\n"
    )
    (root / "tools/mcp_tool_agent.py").write_text(
        "from tools import mcp_tool\n"
        "def refresh_agent_mcp_tools(agent,**kw):\n"
        " agent.tools=mcp_tool.schemas()\n"
        " agent.valid_tool_names={v['function']['name'] for v in agent.tools}\n"
    )
    (root / "hermes_cli").mkdir()
    (root / "hermes_cli/__init__.py").write_text("")
    (root / "hermes_cli/runtime_provider.py").write_text(
        "from pathlib import Path\n"
        "def resolve_runtime_provider(**kw):\n"
        " changed=(Path(__file__).parent.parent/'change-auth').exists()\n"
        " key='fixture-key-new' if changed else 'fixture-key'\n"
        " return {'provider':'openai-codex','api_mode':'codex_responses',"
        f"'base_url':{CODEX_BASE_URL!r},'api_key':key}}\n"
    )
    Runtime(tmp_path / "world.sqlite3", data_origin="session", session_kind="qualification")
    return SimpleNamespace(
        data_dir=tmp_path,
        hermes_python=Path(sys.executable),
        hermes_root=root,
        hermes_auth_root=tmp_path,
        auth="hermes-codex",
        model="fixture",
        api_mode="codex_responses",
        base_url=None,
        vault=None,
        timeout=15,
        resident=True,
        prewarm=False,
        measure_timing=True,
        reasoning_effort="low",
        system_message="Stable test instructions",
    )


def events(args):
    path = args.hermes_root / "events.jsonl"
    return (
        [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        if path.exists()
        else []
    )


def test_two_turns_reuse_agent_and_actual_mcp_with_distinct_authority(
    resident_args, articulated_pose
):
    args = resident_args
    service = ExecutionService(Runtime(args.data_dir / "world.sqlite3", create=False))
    handle = service.acquire_controller(
        source="kinematic", supported_actions=["move"], lease_seconds=60
    )
    snapshot = service.get_world()
    observation = {key: snapshot[key] for key in ("avatar", "objects")}
    observation["pose"] = articulated_pose
    handle.reconcile(observation, stopped=True)
    try:
        with open_text_host(args) as host:
            until(lambda: host.warm_status()["state"] == "ready", timeout=10)
            assert not [event for event in events(args) if event["event"] == "model"]
            assert service.get_world()["conversation"] is None
            pid = host.spare.process.pid
            first = host.start("submit first")
            assert until(host.poll, timeout=10)["status"] == "completed"
            assert host.resident_worker.process.pid == pid and alive(pid)
            assert host.warm()["state"] == "ready" and host.spare is None
            recorded = [event for event in events(args) if event["event"] == "accepted"]
            assert recorded[0]["turn_id"] == first and recorded[0]["status"] == "accepted"
            service.cancel(recorded[0]["request_id"])
            # Data arriving while idle must be included at activation, not from a cached transcript.
            fragment = {
                "source": "user_transcript",
                "start_ms": 0,
                "end_ms": 1,
                "text": "Fresh context",
            }
            host.store.record_live_fragment("fixture", "fresh", fragment)
            second = host.start("submit second")
            assert second != first
            assert until(host.poll, timeout=10)["status"] == "completed"
            assert host.resident_worker.process.pid == pid
            log = events(args)
            assert len([item for item in log if item["event"] == "construct"]) == 1
            connections = [item for item in log if item["event"] == "connect"]
            assert len(connections) == 1
            assert alive(connections[0]["pid"])
            assert connections[0]["turn_id"] == "--call-authority"
            assert [item["turn_id"] for item in log if item["event"] == "tool"] == [
                first,
                first,
                second,
                second,
            ]
            models = [item for item in log if item["event"] == "model"]
            assert models[1]["history"][0]["content"] == "submit first"
            assert "Fresh context" in json.dumps(models[1]["history"])
            assert models[1]["system_message"] == args.system_message
            assert len([item for item in log if item["event"] == "accepted"]) == 2
            assert not [item for item in log if item["event"] == "shutdown"]
            host.cancel()
            assert alive(pid)  # Idle cancellation does not discard a completed resident.
        until(lambda: not alive(pid))
        until(lambda: not alive(connections[0]["pid"]))
    finally:
        handle.release()


def test_interruption_fences_active_mcp_and_kills_resident_and_descendants(resident_args):
    args = resident_args
    with open_text_host(args) as host:
        host.start("wait")
        resident = host.resident_worker
        path = args.hermes_root / "wait-child.pid"
        until(path.exists, timeout=10)
        child = int(path.read_text())
        close = resident.close

        def fenced_close():
            assert host.store.service.get_world()["conversation"] is None
            close()

        resident.close = fenced_close
        host.cancel()
        assert host.resident_worker is None and host.worker is None
        until(lambda: not alive(resident.process.pid) and not alive(child))
        assert all(not alive(item["pid"]) for item in events(args) if item["event"] == "connect")
        host.warm()
        host.start("Correction")
        assert until(host.poll, timeout=10)["status"] == "completed"
        assert host.resident_worker.process.pid != resident.process.pid
        assert host.store.context()["messages"][0]["content"] == "wait"


@pytest.mark.parametrize(
    "failure", ["fail", "bad-history", "native-failed", "native-partial", "native-incomplete"]
)
def test_failed_or_uncommittable_result_never_retains_resident(resident_args, failure):
    with open_text_host(resident_args) as host:
        host.start(failure)
        resident = host.resident_worker
        assert until(host.poll, timeout=10)["status"] == "failed"
        assert host.resident_worker is None
        until(lambda: not alive(resident.process.pid))
        assert host.store.context()["messages"] == [{"role": "user", "content": failure}]


@pytest.mark.parametrize("changed", ["change-auth", "change-schema", "profile"])
def test_resident_changes_fail_closed_before_second_model_call(resident_args, changed):
    args = resident_args
    with open_text_host(args) as host:
        first = host.start("First")
        assert until(host.poll, timeout=10)["status"] == "completed"
        resident = host.resident_worker
        if changed == "profile":
            profile = args.hermes_auth_root / "profiles" / ("promethee-" + first)
            (profile / "config.yaml").write_text("{}")
        else:
            (args.hermes_root / changed).touch()
        host.start("Second")
        assert until(host.poll, timeout=10)["status"] == "failed"
        until(lambda: not alive(resident.process.pid))
        assert len([item for item in events(args) if item["event"] == "model"]) == 1
        assert host.resident_worker is None


def test_resident_transport_refuses_reuse_and_changed_settings(resident_args):
    with open_text_host(resident_args) as host:
        turn = host.start("First")
        assert until(host.poll, timeout=10)["status"] == "completed"
        worker = host.resident_worker
        request = {
            **host.settings,
            "turn_id": turn,
            "session_id": worker.setup["session_id"],
            "message": "Replay",
            "history": [],
        }
        with pytest.raises(ValueError):
            worker.activate(request)
        with pytest.raises(ValueError):
            worker.activate({**request, "turn_id": "turn-" + "a" * 32, "model": "different"})
        assert host.warm_status()["state"] == "ready"


@pytest.mark.parametrize("mutation", ["unactivated", "malformed", "old-turn"])
def test_resident_worker_independently_rejects_bad_activation(resident_args, mutation):
    args = resident_args
    with open_text_host(args) as host:
        first = host.start("First")
        assert until(host.poll, timeout=10)["status"] == "completed"
        worker = host.resident_worker
        request = {
            **host.settings,
            "turn_id": "turn-" + "b" * 32,
            "session_id": worker.setup["session_id"],
            "message": "Rejected",
            "history": [],
        }
        if mutation == "old-turn":
            request["turn_id"] = first
        elif mutation == "malformed":
            request["extra"] = True
        # Deliberately bypass the parent validator to exercise the subprocess boundary.
        worker.current_turn = request["turn_id"]
        worker.requests.put(json.dumps(request) + "\n")
        assert until(worker.poll, timeout=10)["type"] == "error"
        until(lambda: worker.process.poll() is not None)
        assert len([item for item in events(args) if item["event"] == "model"]) == 1


def test_resident_deadline_and_idle_expiry_stop_owned_processes(resident_args):
    args = resident_args
    with open_text_host(args) as host:
        host.start("First")
        assert until(host.poll, timeout=10)["status"] == "completed"
        worker = host.resident_worker
        # A subsequent release uses the shorter test-only idle bound.
        worker.idle_lifetime = 0.15
        host.start("Second")
        assert until(host.poll, timeout=10)["status"] == "completed"
        until(lambda: worker.closed)
        assert host.warm_status()["state"] == "expired"
        host.timeout = 0.1
        host.start("wait")
        resident = host.resident_worker
        assert until(host.poll)["code"] == "deadline_exceeded"
        until(lambda: not alive(resident.process.pid))


def test_resident_is_opt_in_and_rejects_other_auth_before_process_creation():
    with pytest.raises(ValueError, match="Resident mode"):
        with open_text_host(SimpleNamespace(resident="yes")):
            pass
    with pytest.raises(ValueError, match="Codex"):
        with open_text_host(SimpleNamespace(resident=True, auth="api-key")):
            pass
    assert ResidentProcess.resident is True
