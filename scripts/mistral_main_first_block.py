"""First ten frozen main-study slots, Mistral only, no automatic continuation."""
import argparse,asyncio,hashlib,json,os,shutil,subprocess
from datetime import datetime,timedelta,timezone
from pathlib import Path
from benchmark.expanded.execution_authorization import ExecutionPermit,execution_snapshot
from benchmark.expanded.live_generation import LiveGenerator
from benchmark.expanded.planning import allocation,assets_root,check
from benchmark.expanded.provider_generation import save_json
from benchmark.expanded.providers import TokenRates
from benchmark.expanded.spending import DispatchPaused,SpendingLedger
ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'scripts/mistral_main_first_block_plan.json'
FROZEN=ROOT/'expanded_study/study_main_frozen_2026-10-20.json'
MARKER='array-main-mistral-first-block-20261020-v1-prepared'
def load(path):return json.loads(Path(path).read_text())
def require(ok,message):
    if not ok:raise DispatchPaused(message)
def frozen_study(original):
    result=load(FROZEN);restored=json.loads(json.dumps(result))
    for key in ['frozen','paid_execution_authorized','budget_authorized','status']:restored[key]=original[key]
    require(restored==original,'scientific protocol differs from reviewed draft')
    require(all(result[k] is True for k in ['frozen','paid_execution_authorized','budget_authorized']),'main protocol not frozen and approved')
    require(result['proposed_budget_usd']==45 and result['main_outputs']==4320,'unapproved main allocation/budget')
    return result
def load_plan():
    p=load(PLAN)
    require(p['author_approved'] is True and p['maximum_cost_usd']=='1.00' and p['per_request_allowance_usd']=='0.02','Mistral allowance differs')
    require(p['driver_sha256']==hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'driver differs')
    require(p['snapshot']==execution_snapshot(),'reviewed draft or core changed')
    require(p['frozen_study_sha256']==hashlib.sha256(FROZEN.read_bytes()).hexdigest(),'frozen study differs')
    frozen_study(load(assets_root()/'study.json'))
    slots=allocation()[0][:10]
    require(p['slots']==slots and len(slots)==10 and all(s['provider']=='Mistral' and s['cohort']=='main' for s in slots),'outside first frozen main block')
    require(len({s['block_id'] for s in slots})==1 and sum(s['condition']=='C0' for s in slots)==5,'unbalanced first block')
    return p
def workflow_identity():
    require(os.environ.get('GITHUB_REPOSITORY')=='agrawal-priyank/depfailbench' and os.environ.get('GITHUB_RUN_ATTEMPT')=='1','original workflow attempt required')
    require(os.environ.get('GITHUB_REF')=='refs/heads/array-revision-linux-validation' and bool(os.environ.get('GITHUB_RUN_ID') and os.environ.get('GITHUB_SHA')),'revision branch identity missing')
def prior_run_check(path):
    load_plan();workflow_identity();require(not path.exists(),'guard exists')
    q=subprocess.run(['gh','api','--paginate','--slurp','repos/agrawal-priyank/depfailbench/actions/artifacts?per_page=100&name='+MARKER],text=True,capture_output=True)
    require(q.returncode==0,'prior artifact inventory unavailable');pages=json.loads(q.stdout)
    require(bool(pages) and all(p['total_count']==0 and not p['artifacts'] for p in pages),'first main block already prepared; recover evidence without repeating')
    path.parent.mkdir(parents=True,exist_ok=True);save_json(path,{'clear':True,'run':os.environ['GITHUB_RUN_ID'],'commit':os.environ['GITHUB_SHA'],'plan_sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest(),'checked_at_utc':datetime.now(timezone.utc).isoformat()})
def prepare(state,*,guard=None,mock=False):
    plan=load_plan();require(not state.exists(),'existing state must be preserved')
    if not mock:
        workflow_identity();require(os.environ.get('CONFIRM_MISTRAL_MAIN_FIRST_BLOCK')=='true','explicit first-block confirmation required')
        require(guard is not None and guard.is_file(),'prior-run guard missing');proof=load(guard)
        require(proof['clear'] is True and proof['run']==os.environ['GITHUB_RUN_ID'] and proof['commit']==os.environ['GITHUB_SHA'] and proof['plan_sha256']==hashlib.sha256(PLAN.read_bytes()).hexdigest(),'wrong prior guard')
        require(0<=(datetime.now(timezone.utc)-datetime.fromisoformat(proof['checked_at_utc'])).total_seconds()<=3600,'expired guard')
    candidate=state/'frozen_repo/expanded_study';shutil.copytree(assets_root(),candidate);shutil.copyfile(ROOT/'requirements.lock',candidate.parent/'requirements.lock')
    (candidate/'study.json').write_text(json.dumps(frozen_study(load(assets_root()/'study.json')),indent=2)+'\n');check(candidate)
    slots=allocation(candidate)[0][:10];require(slots==plan['slots'],'frozen schedule prefix differs')
    permission={'schema_version':1,'execution_mode':'mock_validation' if mock else 'live','mock_validation_authorized':mock,'paid_execution_authorized':not mock,'cohort':'main','authorized_by':'Priyank Agrawal','authorization_record':plan['authorization_record'],'maximum_cost_usd':'1.00','expires_at_utc':(datetime.now(timezone.utc)+timedelta(hours=72)).isoformat(),'snapshot':execution_snapshot(candidate),'token_rates':plan['token_rates'],'allowed_providers':['Mistral'],'allowed_artifact_ids':[s['artifact_id'] for s in allocation(candidate)[0] if s['provider']=='Mistral']}
    save_json(state/'reviewed_plan.json',plan);save_json(state/'execution_permission.json',permission)
    permit=ExecutionPermit(state/'execution_permission.json',root=candidate);SpendingLedger(state/'spending.sqlite',limit_usd='1.00',simulation_only=False,authorization=permit)
    save_json(state/'main_batch_manifest.json',{'slots':slots,'github_run_id':os.environ.get('GITHUB_RUN_ID'),'github_commit':os.environ.get('GITHUB_SHA'),'synthetic_data':mock,'driver_sha256':plan['driver_sha256'],'expected_responses':10,'cohort':'main','excluded_from_main':False,'total_main_allocation':4320,'no_automatic_follow_on':True,'other_providers_paused':True})
    return {'prepared':True,'expected_main_responses':10,'model_api_calls':0,'synthetic_data':mock}
async def generate(state,index,*,mock_transport=None,mock_credential=None):
    plan=load_plan();require(type(index) is int and index in range(10),'outside first main block');manifest=load(state/'main_batch_manifest.json')
    if manifest['synthetic_data']:
        import httpx
        require(type(mock_transport) is httpx.MockTransport and callable(mock_credential),'mock state requires explicit mock transport and credential')
    else:
        workflow_identity();require(os.environ.get('CONFIRM_MISTRAL_MAIN_FIRST_BLOCK')=='true','explicit main confirmation required')
        require(manifest['github_run_id']==os.environ['GITHUB_RUN_ID'] and manifest['github_commit']==os.environ['GITHUB_SHA'],'wrong workflow')
        require(mock_transport is None and mock_credential is None,'live state cannot substitute mocks')
    require(manifest['driver_sha256']==plan['driver_sha256'],'prepared driver differs')
    slot=manifest['slots'][index];require(slot==plan['slots'][index],'slot differs')
    require(not(state/'artifacts'/slot['artifact_id']).exists(),'existing main attempt/output must never be replaced')
    # Start in the frozen shuffled schedule order and stop after any unresolved predecessor.
    for previous in range(index):
        saved=state/('main_'+str(previous)+'_summary.json');require(saved.is_file(),'previous scheduled output is unfilled; inspect before continuing')
    candidate=state/'frozen_repo/expanded_study';permit=ExecutionPermit(state/'execution_permission.json',root=candidate)
    require(permit.document['allowed_providers']==['Mistral'] and slot['artifact_id'] in permit.document['allowed_artifact_ids'],'outside Mistral permission')
    class Scoped(LiveGenerator):
        def authorize_slot(self,value):
            require(value==slot,'outside exactly selected main response');super().authorize_slot(value)
    ledger=SpendingLedger(state/'spending.sqlite',limit_usd='1.00',simulation_only=False,authorization=permit)
    rates={k:TokenRates(**v) for k,v in plan['token_rates'].items()};options={'wire_transport':mock_transport,'credential_loader':mock_credential} if manifest['synthetic_data'] else {}
    async with Scoped(output=state/'artifacts',ledger=ledger,rates=rates,authorization=permit,root=candidate,**options) as sender:result=await sender.generate(slot,allowance_usd='0.02')
    attempts=[load(p) for p in (state/'artifacts'/slot['artifact_id']).glob('attempt_*/attempt.json')]
    summary={'artifact_id':slot['artifact_id'],'generation_status':result['generation_status'],'elapsed_generation_s':sum(a['elapsed_s'] for a in attempts),'estimated_token_cost_usd':result['estimated_token_cost_usd'],'provider_usage':result['provider_usage'],'invoice_cost_verified':False,'synthetic_data':manifest['synthetic_data'],'functional_tests_performed':False,'cohort':'main','included_in_main':True}
    save_json(state/('main_'+str(index)+'_summary.json'),summary);return {k:v for k,v in summary.items() if k!='provider_usage'}
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['prior-run-check','prepare','generate']);p.add_argument('--state',type=Path,required=True);p.add_argument('--guard',type=Path);p.add_argument('--index',type=int);a=p.parse_args()
    try:
        if a.mode=='prior-run-check':prior_run_check(a.state);r={'prior_check_clear':True,'model_api_calls':0}
        elif a.mode=='prepare':r=prepare(a.state,guard=a.guard)
        else:r=asyncio.run(generate(a.state,a.index))
        print(json.dumps(r),flush=True)
    except Exception as exc:print(json.dumps({'stopped':True,'error_type':type(exc).__name__,'requires_review':True}),flush=True);raise SystemExit(1) from None
