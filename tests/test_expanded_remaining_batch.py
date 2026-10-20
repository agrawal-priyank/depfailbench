"""Remaining provider scope, batch concurrency, account and spending guards."""
import importlib.util,json
from pathlib import Path
from types import SimpleNamespace
import httpx,pytest
from benchmark.expanded.planning import allocation
from benchmark.expanded.providers import TokenRates
from benchmark.expanded.spending import DispatchPaused
spec=importlib.util.spec_from_file_location('remaining_batch',Path(__file__).parents[1]/'scripts/expanded_remaining_validation.py')
batch=importlib.util.module_from_spec(spec);spec.loader.exec_module(batch)


@pytest.fixture(autouse=True)
def current_core_mock_plans(tmp_path,monkeypatch):
 original_select=batch.select_provider
 def select(provider):
  original_select(provider)
  plan=json.loads(batch.PLAN_PATH.read_text());plan['snapshot']=batch.execution_snapshot()
  path=tmp_path/(provider+'_mock_plan.json');path.write_text(json.dumps(plan))
  monkeypatch.setattr(batch,'PLAN_PATH',path)
 monkeypatch.setattr(batch,'select_provider',select)

@pytest.fixture(params=['Mistral','Google','xAI'])
def selected(request):
 batch.select_provider(request.param);return request.param


def test_explicit_provider_required(monkeypatch):
 monkeypatch.setattr(batch,'PROVIDER',None);monkeypatch.setattr(batch,'PLAN_PATH',None)
 with pytest.raises(DispatchPaused):batch.load_plan()
 with pytest.raises(DispatchPaused):batch.select_provider('OpenAI')


def test_exact_allocation_limits_and_prior_marker(selected):
 p=batch.load_plan();s=batch.SPECS[selected]
 assert len(p['slots'])==s['count'] and p['concurrency']==s['concurrency']
 assert len({x['artifact_id'] for x in p['slots']})==s['count']
 assert all(x['cohort']=='validation' and x['provider']==selected for x in p['slots'])

@pytest.mark.parametrize('limit',['0','-1','999','NaN'])
def test_bad_budget_creates_no_state(tmp_path,selected,limit):
 with pytest.raises(DispatchPaused):batch.prepare(tmp_path/'state',maximum_cost_usd=limit)
 assert not (tmp_path/'state').exists()


def test_live_needs_confirmation_first_attempt_and_guard(tmp_path,selected,monkeypatch):
 monkeypatch.delenv('CONFIRM_PAID_GENERATION',raising=False)
 with pytest.raises(DispatchPaused):batch.prepare(tmp_path/'state',maximum_cost_usd=batch.SPECS[selected]['limit'],live=True)
 monkeypatch.setenv('CONFIRM_PAID_GENERATION','true');monkeypatch.setenv('GITHUB_RUN_ATTEMPT','2')
 with pytest.raises(DispatchPaused):batch.prepare(tmp_path/'state',maximum_cost_usd=batch.SPECS[selected]['limit'],live=True)
 monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1')
 with pytest.raises(DispatchPaused,match='prior batch'):batch.prepare(tmp_path/'state',maximum_cost_usd=batch.SPECS[selected]['limit'],live=True)
 assert not (tmp_path/'state').exists()


async def test_complete_provider_mock_and_duplicate_protection(tmp_path,selected):
 report=await batch.mock_rehearsal(tmp_path/'state')
 assert report['complete'] and report['programs']==batch.SPECS[selected]['count']
 assert report['mock_wire_calls']==report['programs'] and report['model_generation_calls']==0
 assert report['duplicate_dispatch_blocked'] and report['credential_canary_absent']


async def test_main_and_foreign_provider_block_before_credentials(tmp_path,selected):
 state=tmp_path/'state';batch.prepare(state,maximum_cost_usd=batch.SPECS[selected]['limit'])
 plan,manifest,permit,ledger=batch.context(state);calls=[];rates={k:TokenRates(**v) for k,v in plan['token_rates'].items()}
 async with batch.ScopedGenerator(output=state/'artifacts',ledger=ledger,rates=rates,authorization=permit,
   credential_loader=lambda p:calls.append(p),wire_transport=httpx.MockTransport(lambda r:None)) as generator:
  for slot in (next(s for s in allocation()[0] if s['provider']==selected),next(s for s in allocation()[1] if s['provider']!=selected)):
   with pytest.raises(DispatchPaused):await generator.generate(slot,allowance_usd='.01')
 assert calls==[] and ledger.snapshot()['attempts']==[]


async def test_metadata_is_only_selected_model_gets_and_correct_auth(tmp_path,selected):
 state=tmp_path/'state';batch.prepare(state,maximum_cost_usd=batch.SPECS[selected]['limit']);calls=[]
 def handler(request):
  assert request.method=='GET' and request.url.query==b''
  assert request.headers.get('x-goog-api-key')=='synthetic' if selected=='Google' else request.headers['authorization']=='Bearer synthetic'
  model=request.url.path.rsplit('/',1)[-1];calls.append(model)
  return httpx.Response(200,json={'name':'models/'+model} if selected=='Google' else {'id':model},request=request)
 report=await batch.access_check(state,mock_transport=httpx.MockTransport(handler),mock_credential=lambda p:'synthetic')
 assert report['passed'] and report['synthetic_data'] and report['model_generation_calls']==0
 assert set(calls)==set(batch.SPECS[selected]['allowances'])


async def test_synthetic_account_cannot_call_real_endpoint(tmp_path,selected):
 state=tmp_path/'state';batch.prepare(state,maximum_cost_usd=batch.SPECS[selected]['limit'])
 with pytest.raises(DispatchPaused,match='synthetic'):await batch.access_check(state)


async def test_unknown_usage_preserves_and_pauses_next_slot(tmp_path,selected):
 state=tmp_path/'state';batch.prepare(state,maximum_cost_usd=batch.SPECS[selected]['limit']);calls=[]
 def handler(request):
  calls.append(1);raw=batch.fixture(selected,json.loads(request.content)['model']);raw.pop('usage')
  return httpx.Response(200,json=raw,request=request)
 wire=httpx.MockTransport(handler)
 first=await batch.generate_slot(state,0,mock_transport=wire,mock_credential=lambda p:'synthetic')
 assert first['estimated_token_cost_usd'] is None
 with pytest.raises(DispatchPaused):await batch.generate_slot(state,1,mock_transport=wire,mock_credential=lambda p:'synthetic')
 assert calls==[1]


def test_prior_marker_filter_prevents_duplicate_even_expired(tmp_path,selected,monkeypatch):
 for k,v in {'GITHUB_RUN_ATTEMPT':'1','GITHUB_REPOSITORY':'agrawal-priyank/depfailbench','GITHUB_RUN_ID':'synthetic','GITHUB_SHA':'synthetic'}.items():monkeypatch.setenv(k,v)
 marker=batch.load_plan()['prepared_artifact_name']
 def run(args,**kw):
  assert 'name='+marker in args[-1]
  return SimpleNamespace(returncode=0,stdout=json.dumps([{'total_count':1,'artifacts':[{'name':marker,'expired':True}]}]))
 monkeypatch.setattr(batch.subprocess,'run',run)
 with pytest.raises(DispatchPaused,match='already has saved state'):batch.prior_run_check(tmp_path/'guard.json')
 assert not (tmp_path/'guard.json').exists()


def test_first_guard_creates_missing_checkpoint_parent_without_provider_access(tmp_path,selected,monkeypatch):
 for k,v in {'GITHUB_RUN_ATTEMPT':'1','GITHUB_REPOSITORY':'agrawal-priyank/depfailbench','GITHUB_RUN_ID':'synthetic','GITHUB_SHA':'synthetic'}.items():monkeypatch.setenv(k,v)
 monkeypatch.setattr(batch.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout=json.dumps([{'total_count':0,'artifacts':[]}])) )
 path=tmp_path/'missing/results/prior_guard.json'
 report=batch.prior_run_check(path)
 assert path.is_file() and report['clear'] and report['model_generation_calls']==0
 before=path.read_bytes()
 with pytest.raises(DispatchPaused,match='already exists'):batch.prior_run_check(path)
 assert path.read_bytes()==before
