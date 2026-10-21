"""One author-approved medium-effort feasibility sample; no main-study execution."""
import argparse,asyncio,json,hashlib,os,shutil
from pathlib import Path
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import httpx
from benchmark.expanded.execution_authorization import ExecutionPermit,execution_snapshot
from benchmark.expanded.live_generation import LiveGenerator
from benchmark.expanded.live_transport import environment_credential
from benchmark.expanded.planning import assets_root,allocation,check
from benchmark.expanded.providers import TokenRates
from benchmark.expanded.provider_generation import save_json
from benchmark.expanded.spending import SpendingLedger,DispatchPaused

ROOT=Path(__file__).resolve().parents[1]
MARKER='grok-medium-sample-20261020-v1-prepared'
def load(p):return json.loads(Path(p).read_text())
def require(ok,message):
    if not ok:raise DispatchPaused(message)
def candidate_study(original):
    result=json.loads(json.dumps(original));config=next(c for c in result['configurations'] if c['provider']=='xAI')
    require(config['id']=='grok_4_7' and config['generation_settings']['reasoning_effort']=='high','original configuration differs')
    config['id']='grok_4_7_medium';config['generation_settings']['reasoning_effort']='medium'
    require(result['frozen'] is False and result['paid_execution_authorized'] is False,'main remains disabled')
    return result

def prepare(state):
    require(not state.exists(),'sample already prepared; recover rather than repeat')
    old=load(ROOT/'scripts/expanded_xai_request_recovery_plan.json')
    require(old['snapshot']==execution_snapshot(),'reviewed core/assets differ')
    candidate=state/'candidate_repo/expanded_study';shutil.copytree(assets_root(),candidate)
    shutil.copyfile(ROOT/'requirements.lock',candidate.parent/'requirements.lock')
    (candidate/'study.json').write_text(json.dumps(candidate_study(load(assets_root()/'study.json')),indent=2)+'\n')
    check(candidate);slot=next(s for s in allocation(candidate)[1] if s['configuration_id']=='grok_4_7_medium' and s['task']=='E5' and s['condition']=='C1')
    review={'author':'Priyank Agrawal','authorization':'Test Grok medium first; one feasibility response initially, within the existing$12 Grok envelope. No main authorization.',
        'known_prior_token_cost_estimate_usd':'0.526958','cancelled_request_budget_reservation_retained_usd':'1',
        'prior_billing_observation':'Author reports no charge shown and free usage83%; no zero economic-cost or invoice claim.',
        'prior_archive_sha256':'4762ae896887ff1b662e902b2874633a22684997b159eb001a0ef671b998e3ed',
        'maximum_new_pilot_allowance_usd':'1','aggregate_known_reserved_and_sample_allowance_usd':'2.526958','overall_grok_allowance_usd':'12',
        'change':'only high to medium reasoning; new configuration identity; same prompt/model/sampling/tools/output cap',
        'model_api_calls':0,'main_outputs':0}
    require(Decimal(review['aggregate_known_reserved_and_sample_allowance_usd'])<=Decimal('12'),'aggregate allowance exceeded')
    save_json(state/'budget_review.json',review)
    permission={'schema_version':1,'execution_mode':'live','paid_execution_authorized':True,'cohort':'validation','authorized_by':'Priyank Agrawal',
        'authorization_record':review['authorization'],'maximum_cost_usd':'1','expires_at_utc':(datetime.now(timezone.utc)+timedelta(hours=12)).isoformat(),
        'snapshot':execution_snapshot(candidate),'token_rates':old['token_rates'],'allowed_providers':['xAI'],'allowed_artifact_ids':[slot['artifact_id']]}
    save_json(state/'execution_permission.json',permission);permit=ExecutionPermit(state/'execution_permission.json',root=candidate)
    ledger=SpendingLedger(state/'spending.sqlite',limit_usd='1',simulation_only=False,authorization=permit)
    save_json(state/'sample_manifest.json',{'slot':slot,'github_run_id':os.environ.get('GITHUB_RUN_ID'),'github_commit':os.environ.get('GITHUB_SHA'),
        'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'excluded_from_main':True,'expected_responses':1,'main_outputs':0})
    return {'prepared':True,'expected_responses':1,'model_api_calls':0}

async def generate(state):
    require(os.environ.get('CONFIRM_GROK_MEDIUM_SAMPLE')=='true' and os.environ.get('GITHUB_RUN_ATTEMPT')=='1','original authorized sample workflow required')
    require(os.environ.get('GITHUB_REF')=='refs/heads/array-revision-linux-validation','revision branch required')
    manifest=load(state/'sample_manifest.json');slot=manifest['slot'];candidate=state/'candidate_repo/expanded_study'
    require(manifest['github_run_id']==os.environ.get('GITHUB_RUN_ID') and manifest['github_commit']==os.environ.get('GITHUB_SHA'),'sample workflow differs')
    require(manifest['driver_sha256']==hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'sample driver differs')
    permit=ExecutionPermit(state/'execution_permission.json',root=candidate)
    require(permit.document['allowed_artifact_ids']==[slot['artifact_id']] and slot['task']=='E5' and slot['condition']=='C1','outside one exact feasibility coordinate')
    require(not (state/'artifacts'/slot['artifact_id']).exists(),'existing response/attempt must never be replaced')
    class Scoped(LiveGenerator):
        def authorize_slot(self,s):
            require(s==slot,'outside the single permitted medium coordinate');super().authorize_slot(s)
    ledger=SpendingLedger(state/'spending.sqlite',limit_usd='1',simulation_only=False,authorization=permit)
    rates={k:TokenRates(**v) for k,v in permit.document['token_rates'].items()}
    async with Scoped(output=state/'artifacts',ledger=ledger,rates=rates,authorization=permit,root=candidate) as sender:
        result=await sender.generate(slot,allowance_usd='1')
    attempts=[load(p) for p in (state/'artifacts'/slot['artifact_id']).glob('attempt_*/attempt.json')]
    out={'complete':True,'artifact_id':slot['artifact_id'],'generation_status':result['generation_status'],
        'elapsed_generation_s':sum(a['elapsed_s'] for a in attempts),'estimated_token_cost_usd':result['estimated_token_cost_usd'],
        'provider_usage':result['provider_usage'],'invoice_cost_verified':False,'ledger':ledger.snapshot(),
        'functional_tests_performed':False,'main_outputs':0,'no_automatic_additional_generation':True}
    save_json(state/'sample_summary.json',out);return out

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['prepare','generate']);parser.add_argument('--state',type=Path,required=True);a=parser.parse_args()
    try:
        r=prepare(a.state) if a.mode=='prepare' else asyncio.run(generate(a.state))
        print(json.dumps({k:v for k,v in r.items() if k not in ('provider_usage','ledger')}),flush=True)
    except Exception as exc:
        print(json.dumps({'stopped':True,'error_type':type(exc).__name__,'requires_review':True}),flush=True);raise SystemExit(1) from None
