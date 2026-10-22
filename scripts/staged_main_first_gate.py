"""First balanced block per provider in a fresh main campaign; stop after forty.

No later batch can be dispatched by this driver. Evaluations run in separate,
credential-free jobs; continuation needs independently reviewed saved evidence.
"""
import argparse, asyncio, hashlib, json, os, shutil, subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import httpx
from benchmark.expanded.collect import artifact_manifest
from benchmark.expanded.execution_authorization import ExecutionPermit, execution_snapshot
from benchmark.expanded.live_generation import LiveGenerator
from benchmark.expanded.planning import allocation, assets_root, check
from benchmark.expanded.provider_generation import save_json
from benchmark.expanded.provider_dry_run import fixture, sse_bytes, stream_events
from benchmark.expanded.providers import TokenRates
from benchmark.expanded.spending import DispatchPaused, SpendingLedger

ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'scripts/staged_main_first_gate_plan.json'
FROZEN=ROOT/'expanded_study/study_main_frozen_2026-10-21.json'
CAMPAIGN='main-clarified-prompts-20261021-fresh-v1'
PROVIDERS=('Anthropic','OpenAI','Google','Mistral')


def load(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def require(ok,message):
    if not ok:raise DispatchPaused(message)


def first_slots(provider,root=None):
    require(provider in PROVIDERS,'Provider outside the retained panel')
    slots=[s for s in allocation(root)[0] if s['provider']==provider][:10]
    require(len(slots)==10 and len({s['block_id'] for s in slots})==1 and
            sum(s['condition']=='C0' for s in slots)==5 and all(s['round']==1 for s in slots),
            'First block must retain the frozen balanced schedule')
    return slots


def frozen_study():
    original=load(assets_root()/'study.json');frozen=load(FROZEN)
    approved={'protocol_version','status','frozen','paid_execution_authorized','budget_authorized',
              'cost_note','prompt_amendment','campaign_namespace','staged_execution'}
    require({k:v for k,v in original.items() if k not in approved}==
            {k:v for k,v in frozen.items() if k not in approved},'Scientific design changed')
    require(all(frozen[k] is True for k in ['frozen','paid_execution_authorized','budget_authorized']) and
            frozen['campaign_namespace']==CAMPAIGN and frozen['main_outputs']==4320 and
            frozen['proposed_budget_usd']==45,'Fresh main freeze missing')
    amendment=dict(frozen['prompt_amendment']);old=dict(original['prompt_amendment'])
    amendment.pop('main_cohort_handling');old.pop('main_cohort_handling')
    require(amendment==old,'Task amendment changed beyond the reviewed cohort handling')
    return frozen


def plan():
    p=load(PLAN)
    require(p['author_approved'] is True and p['campaign_namespace']==CAMPAIGN and
            p['stage']=='first_40_main_outputs_only' and p['automatic_continuation'] is False,
            'First-gate scope/authorization differs')
    require(p['snapshot']==execution_snapshot() and p['driver_sha256']==sha(Path(__file__)) and
            p['frozen_study_sha256']==sha(FROZEN),'Frozen software/assets changed')
    require(p['evaluation_driver_sha256']==sha(ROOT/'scripts/evaluate_staged_main_first_gate.py') and
            p['host_recorder_sha256']==sha(ROOT/'scripts/record_evaluation_host.py'),'Evaluation or hardware recorder changed')
    require(p['workflow_sha256']==sha(ROOT/'.github/workflows/full-study.yml') and
            p['software_gate_driver_sha256']==sha(ROOT/'scripts/staged_main_software_gate.py'),'Workflow or software gate changed')
    require(set(p['slots'])==set(PROVIDERS) and all(p['slots'][v]==first_slots(v) for v in PROVIDERS),
            'Outside the four first balanced blocks')
    require(p['cumulative_caps_usd']=={'OpenAI':'18','Anthropic':'21','Google':'4','Mistral':'2'} and
            sum(Decimal(v) for v in p['cumulative_caps_usd'].values())==45,'Overall envelope changed')
    require(p['prior_current_envelope_token_estimate_usd']=={'Anthropic':'0.373006','OpenAI':'0.3175636','Google':'0.05778750','Mistral':'0.4781926'},
            'Previously incurred cost offsets changed')
    for provider in PROVIDERS:
        require(Decimal(p['new_campaign_caps_usd'][provider])==
                Decimal(p['cumulative_caps_usd'][provider])-Decimal(p['prior_current_envelope_token_estimate_usd'][provider]),
                'Fresh ledger must reserve room for previous charges')
    frozen_study();check()
    return p


def identity():
    require(os.environ.get('GITHUB_REPOSITORY')=='agrawal-priyank/depfailbench' and
            os.environ.get('GITHUB_REF')=='refs/heads/array-revision-linux-validation' and
            os.environ.get('GITHUB_RUN_ATTEMPT')=='1' and
            os.environ.get('GITHUB_RUN_ID') and os.environ.get('GITHUB_SHA'),
            'Original revision-branch workflow required')


def marker(provider):return CAMPAIGN+'-'+provider.lower()+'-first-gate-prepared'


def prior(provider,path):
    p=plan();identity();require(provider in PROVIDERS and not path.exists(),'Wrong provider or existing guard')
    q=subprocess.run(['gh','api','--paginate','--slurp','repos/agrawal-priyank/depfailbench/actions/artifacts?per_page=100&name='+marker(provider)],text=True,capture_output=True)
    require(q.returncode==0,'Prior artifact inventory unavailable')
    pages=json.loads(q.stdout)
    require(pages and all(x['total_count']==0 and not x['artifacts'] for x in pages),
            'Campaign already prepared; recover retained evidence without redispatch')
    path.parent.mkdir(parents=True,exist_ok=True)
    save_json(path,{'provider':provider,'clear':True,'run':os.environ['GITHUB_RUN_ID'],
                   'commit':os.environ['GITHUB_SHA'],'plan_sha256':sha(PLAN),
                   'at':datetime.now(timezone.utc).isoformat()})


def prepare(provider,state,guard=None,mock=False):
    p=plan();require(provider in PROVIDERS and not state.exists(),'Preserve existing campaign state')
    if not mock:
        identity();require(os.environ.get('CONFIRM_FRESH_MAIN_FIRST_GATE')=='true','First-gate confirmation missing')
        require(guard is not None and guard.is_file(),'Prior marker guard required');g=load(guard)
        require(g['clear'] is True and g['provider']==provider and g['run']==os.environ['GITHUB_RUN_ID'] and
                g['commit']==os.environ['GITHUB_SHA'] and g['plan_sha256']==sha(PLAN) and
                0<=(datetime.now(timezone.utc)-datetime.fromisoformat(g['at'])).total_seconds()<=3600,
                'Wrong or expired prior guard')
    root=state/'frozen_repo/expanded_study'
    shutil.copytree(assets_root(),root);shutil.copyfile(ROOT/'requirements.lock',root.parent/'requirements.lock')
    (root/'study.json').write_text(json.dumps(frozen_study(),indent=2)+'\n');check(root)
    slots=first_slots(provider,root);require(slots==p['slots'][provider],'Frozen schedule differs')
    permission={'schema_version':1,'execution_mode':'mock_validation' if mock else 'live',
                'mock_validation_authorized':mock,'paid_execution_authorized':not mock,'cohort':'main',
                'authorized_by':'Priyank Agrawal','authorization_record':p['authorization_record'],
                'maximum_cost_usd':p['new_campaign_caps_usd'][provider],
                'expires_at_utc':(datetime.now(timezone.utc)+timedelta(hours=48)).isoformat(),
                'snapshot':execution_snapshot(root),'token_rates':p['token_rates'],
                'allowed_providers':[provider],'allowed_artifact_ids':[s['artifact_id'] for s in slots]}
    save_json(state/'reviewed_plan.json',p);save_json(state/'execution_permission.json',permission)
    permit=ExecutionPermit(state/'execution_permission.json',root=root)
    SpendingLedger(state/'spending.sqlite',limit_usd=p['new_campaign_caps_usd'][provider],simulation_only=False,authorization=permit)
    save_json(state/'run_manifest.json',{'campaign_namespace':CAMPAIGN,'provider':provider,'slots':slots,
        'github_run_id':os.environ.get('GITHUB_RUN_ID'),'github_commit':os.environ.get('GITHUB_SHA'),
        'synthetic_data':mock,'plan_sha256':sha(PLAN),'expected_responses':10,'cohort':'main',
        'included_in_fresh_main':True,'reused_original_sources':0,'no_automatic_continuation':True,
        'prior_current_envelope_token_estimate_usd':p['prior_current_envelope_token_estimate_usd'][provider]})
    return {'prepared':True,'provider':provider,'main_outputs':10,'model_api_calls':0}


def context(provider,state):
    p=plan();m=load(state/'run_manifest.json');root=state/'frozen_repo/expanded_study'
    require(load(state/'reviewed_plan.json')==p and m['provider']==provider and m['slots']==p['slots'][provider] and
            m['plan_sha256']==sha(PLAN) and m['campaign_namespace']==CAMPAIGN,'Prepared scope differs')
    permit=ExecutionPermit(state/'execution_permission.json',root=root)
    require(permit.document['allowed_providers']==[provider] and
            permit.document['allowed_artifact_ids']==[s['artifact_id'] for s in m['slots']],
            'Permission extends outside this first block')
    require(m['synthetic_data']==(permit.document['execution_mode']=='mock_validation'),'Mock/live state differs')
    if not m['synthetic_data']:
        identity();require(os.environ.get('CONFIRM_FRESH_MAIN_FIRST_GATE')=='true' and
            m['github_run_id']==os.environ['GITHUB_RUN_ID'] and m['github_commit']==os.environ['GITHUB_SHA'],
            'Live workflow identity differs')
    ledger=SpendingLedger(state/'spending.sqlite',limit_usd=p['new_campaign_caps_usd'][provider],simulation_only=False,authorization=permit)
    return p,m,root,permit,ledger


async def pair(provider,state,index,wire=None,key=None):
    require(type(index) is int and 0<=index<5,'Outside first five pairs')
    p,m,root,permit,ledger=context(provider,state)
    require(not(state/f'pair_{index:02d}.json').exists(),'Existing pair must not be repeated')
    require(all((state/f'pair_{i:02d}.json').is_file() for i in range(index)),
            'Missing predecessor; preserve partial calls and investigate')
    selected=m['slots'][index*2:index*2+2]
    require(all(not(state/'artifacts'/s['artifact_id']).exists() for s in selected),
            'An attempt/output exists; never replace it automatically')
    if m['synthetic_data']:
        require(type(wire) is httpx.MockTransport and callable(key),'Explicit mock transport/credential required')
    else:require(wire is None and key is None,'Live state cannot substitute mocks')
    def credential(requested):
        require(requested==provider,'Wrong provider credential scope')
        value=os.environ.get('FRESH_MAIN_PROVIDER_API_KEY')
        require(isinstance(value,str) and value and not any(c in value for c in '\r\n'),'Provider secret missing/invalid')
        return value
    class Scoped(LiveGenerator):
        def authorize_slot(self,s):
            require(s in selected and s['provider']==provider and s['cohort']=='main','Outside current pair')
            super().authorize_slot(s)
    rates={name:TokenRates(**v) for name,v in p['token_rates'].items()}
    async with Scoped(output=state/'artifacts',ledger=ledger,rates=rates,authorization=permit,root=root,
                      wire_transport=wire,credential_loader=key or credential) as sender:
        results=await asyncio.gather(*(sender.generate(s,allowance_usd=p['per_request_allowance_usd'][s['model_id']]) for s in selected),return_exceptions=True)
    require(not any(isinstance(r,BaseException) for r in results),'Pair paused; preserve all attempts and review')
    rows=[{k:r[k] for k in ['artifact_id','generation_status','estimated_token_cost_usd']} for r in results]
    save_json(state/f'pair_{index:02d}.json',rows);return rows


def summarize(provider,state):
    p,m,root,permit,ledger=context(provider,state)
    require(all((state/f'pair_{i:02d}.json').is_file() for i in range(5)),'Incomplete first block')
    require({f.name for f in (state/'artifacts').iterdir()}=={s['artifact_id'] for s in m['slots']},'Missing or extra outputs')
    configs={c['id']:c for c in load(root/'study.json')['configurations']};rows=[]
    for slot in m['slots']:
        art=state/'artifacts'/slot['artifact_id'];metadata=load(art/'metadata.json')
        if m['synthetic_data']:
            require(metadata['synthetic_data'] is True and all(metadata[k]==v for k,v in slot.items()),'Invalid mock coordinate')
            require((art/'prompt.txt').read_bytes()==(root/'prompts'/f"{slot['task']}_{slot['condition']}.md").read_bytes(),'Mock prompt mismatch')
        else:require(not artifact_manifest(art,slot,configs[slot['configuration_id']],root)['synthetic_data'],'Synthetic source in real main evidence')
        rows.append({k:metadata[k] for k in ['artifact_id','generation_status','estimated_token_cost_usd']})
    budget=ledger.snapshot()
    require(not budget['held'] and not budget['pauses'] and all(a['state']=='settled' for a in budget['attempts']),
            'Unsettled usage or financial pause requires review')
    report={'provider':provider,'complete':True,'programs':10,'cohort':'main','synthetic_data':m['synthetic_data'],
            'campaign_namespace':CAMPAIGN,'estimated_token_cost_usd':str(Decimal(budget['cost'])/Decimal(budget['units_per_usd'])),
            'invoice_cost_verified':False,'rows':rows,'ledger':budget,'no_automatic_continuation':True,
            'functional_correctness_not_inferred':True}
    save_json(state/'generation_summary.json',report)
    return {k:v for k,v in report.items() if k not in {'rows','ledger'}}


async def mock(provider,state):
    prepare(provider,state,mock=True);calls=[];canary='OFFLINE-FIRST-GATE-CREDENTIAL-CANARY'
    def handler(request):
        body=json.loads(request.content);calls.append(body)
        model=body.get('model','gemini-3.8-flash')
        return httpx.Response(200,headers={'content-type':'text/event-stream'},
            content=sse_bytes(stream_events(provider,fixture(provider,model))),request=request)
    for index in range(5):await pair(provider,state,index,httpx.MockTransport(handler),lambda p:canary)
    require(len(calls)==10,'Wrong mocked request count')
    require(all(canary.encode() not in f.read_bytes() for f in state.rglob('*') if f.is_file()),'Credential canary persisted')
    return {**summarize(provider,state),'mock_requests':10,'credential_canary_absent':True}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['check','prior','prepare','pair','summarize','mock'])
    p.add_argument('--provider',choices=PROVIDERS,required=True);p.add_argument('--state',type=Path,required=True)
    p.add_argument('--guard',type=Path);p.add_argument('--index',type=int);a=p.parse_args()
    try:
        if a.mode=='check':plan();result={'passed':True,'model_api_calls':0}
        elif a.mode=='prior':prior(a.provider,a.state);result={'clear':True,'model_api_calls':0}
        elif a.mode=='prepare':result=prepare(a.provider,a.state,a.guard)
        elif a.mode=='pair':result=asyncio.run(pair(a.provider,a.state,a.index))
        elif a.mode=='mock':result=asyncio.run(mock(a.provider,a.state))
        else:result=summarize(a.provider,a.state)
        print(json.dumps(result),flush=True)
    except Exception as e:
        print(json.dumps({'stopped':True,'error_type':type(e).__name__,'requires_review':True}),flush=True)
        raise SystemExit(1) from None
