"""Continue only fifteen unfilled validation coordinates after reviewed budget amendment.

Original archive/ledger and completed response are immutable. A separately
labelled ledger COPY carries forward all charges and records the explicit
allowance/permit amendment. No model request is made on import or preparation.
"""
import argparse,asyncio,hashlib,json,os,shutil,sqlite3,subprocess
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
import httpx
from benchmark.expanded.collect import artifact_manifest
from benchmark.expanded.execution_authorization import ExecutionPermit,execution_snapshot
from benchmark.expanded.live_generation import LiveGenerator
from benchmark.expanded.live_transport import environment_credential
from benchmark.expanded.planning import allocation,assets_root
from benchmark.expanded.provider_generation import save_json
from benchmark.expanded.providers import TokenRates
from benchmark.expanded.spending import DispatchPaused,SpendingLedger,units
from evaluate_saved_openai_validation import extract_checked

SCRIPT=Path(__file__).resolve();PLAN=SCRIPT.with_suffix('.json')
SOURCE_RUN=39508708273;SOURCE_COMMIT='c487cb1261f047b5c64f926eecc17314006d8aa9';SOURCE_ARTIFACT=12304899905
SOURCE_SHA='3390e30dec40a3e225f6e5054351c9b102e049dbabb940f5f9d2863503af8d9a'
FIRST='validation_E5_grok_4_7_C1';BATCH='xai-budget-continuation-20261020-v3'

def load(path):return json.loads(Path(path).read_text())
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def require(test,message):
    if not test:raise DispatchPaused(message)

def load_plan():
    p=load(PLAN);slots=[s for s in allocation()[1] if s['provider']=='xAI']
    require(p['driver_sha256']==digest(SCRIPT) and p['snapshot']==execution_snapshot(),'reviewed software/assets changed')
    require(p['slots']==slots[1:] and p['retained_slot']==slots[0] and slots[0]['artifact_id']==FIRST and len(slots)==16,'exact original15 unfilled coordinates required')
    require(p['maximum_cost_usd']=='12' and p['per_attempt_allowance_usd']=='1' and p['batch_id']==BATCH,'budget amendment scope differs')
    require(p['previous_archive_sha256']==SOURCE_SHA and p['provider']=='xAI','source/provider differs')
    return p

def workflow_identity():
    require(os.environ.get('GITHUB_REPOSITORY')=='agrawal-priyank/depfailbench' and os.environ.get('GITHUB_RUN_ATTEMPT')=='1'
            and os.environ.get('GITHUB_REF')=='refs/heads/array-revision-linux-validation','original revision-branch workflow required')
    require(bool(os.environ.get('GITHUB_RUN_ID')) and bool(os.environ.get('GITHUB_SHA')),'workflow identity absent')

def prior_run_check(guard):
    p=load_plan();workflow_identity();guard=Path(guard)
    require(not guard.exists(),'existing guard must be recovered, never overwritten')
    def api(path,binary=False):
        q=subprocess.run(['gh','api','repos/agrawal-priyank/depfailbench/'+path],capture_output=True)
        require(q.returncode==0,'prior evidence metadata unavailable')
        return q.stdout if binary else json.loads(q.stdout)
    marker=api('actions/artifacts?per_page=100&name='+BATCH+'-prepared')
    require(marker['total_count']==0 and not marker['artifacts'],'budget continuation already prepared; recover rather than repeat')
    meta=api(f'actions/artifacts/{SOURCE_ARTIFACT}')
    require(meta['workflow_run']['id']==SOURCE_RUN and meta['workflow_run']['head_sha']==SOURCE_COMMIT
            and meta['digest']=='sha256:'+SOURCE_SHA and not meta['expired'],'original artifact metadata differs')
    jobs=api(f'actions/runs/{SOURCE_RUN}/jobs?per_page=100')['jobs'];job=next(j for j in jobs if j['name']=='grok-request-recovery')
    steps={s['name']:s['conclusion'] for s in job['steps']}
    require(job['conclusion']=='failure' and job['head_sha']==SOURCE_COMMIT and steps['Generate excluded validation group 0']=='success'
            and steps['Generate excluded validation group 1']=='failure' and all(steps[f'Generate excluded validation group {i}']=='skipped' for i in range(2,16)), 'prior execution history differs')
    data=api(f'actions/artifacts/{SOURCE_ARTIFACT}/zip',True);require(hashlib.sha256(data).hexdigest()==SOURCE_SHA,'original archive digest differs')
    guard.parent.mkdir(parents=True,exist_ok=True)
    with guard.with_suffix('.zip').open('xb') as f:f.write(data)
    save_json(guard,{'batch_id':BATCH,'plan_sha256':digest(PLAN),'source_archive_sha256':SOURCE_SHA,'github_run_id':os.environ['GITHUB_RUN_ID'],
                    'github_commit':os.environ['GITHUB_SHA'],'checked_at_utc':datetime.now(timezone.utc).isoformat(),'model_api_calls':0})

def verify_original(state,p):
    state=Path(state);manifest=load(state/'run_manifest.json');oldplan=load(state/'reviewed_plan.json')
    require(manifest['github_run_id']==str(SOURCE_RUN) and manifest['github_commit']==SOURCE_COMMIT and manifest['synthetic_data'] is False,'original run differs')
    require(oldplan['snapshot']==p['snapshot'] and oldplan['slots']==[p['retained_slot'],*p['slots']],'original allocation/software differs')
    require({d.name for d in (state/'artifacts').iterdir()}=={FIRST},'unexpected existing outputs; do not replace')
    config=next(c for c in load(assets_root()/'study.json')['configurations'] if c['id']==p['retained_slot']['configuration_id'])
    artifact=artifact_manifest(state/'artifacts'/FIRST,p['retained_slot'],config,assets_root())
    require(artifact['metadata']['generation_status']=='completed' and artifact['metadata']['estimated_token_cost_usd']=='0.526958','retained response differs')
    checkpoint=load(state/'checkpoint_00.json')['ledger']
    require(checkpoint['cost']==526958000 and checkpoint['held']==0 and len(checkpoint['attempts'])==1,'original accounting differs')
    db=sqlite3.connect((state/'spending.sqlite').resolve().as_uri()+'?mode=ro&immutable=1',uri=True);db.row_factory=sqlite3.Row
    try:
        require([dict(r) for r in db.execute('SELECT * FROM attempts')]==checkpoint['attempts'],'original ledger differs from checkpoint')
        require([dict(r) for r in db.execute('SELECT * FROM pauses')]==[{'provider':'*','reason':'observed cost exceeded allowance or overall limit; review required'}],'original pause differs')
        require(dict(db.execute('SELECT name,value FROM settings'))['limit']=='8000000000','original budget changed')
    finally:db.close()
    return artifact

def migrate_ledger(original,destination,permit,review_path):
    """Amend a new COPY explicitly; never erase a charge, attempt or original."""
    original,destination=Path(original),Path(destination);require(not destination.exists(),'ledger copy already exists')
    before=digest(original);shutil.copyfile(original,destination)
    db=sqlite3.connect(destination);db.row_factory=sqlite3.Row
    try:
        old=dict(db.execute('SELECT name,value FROM settings'));require(old['limit']=='8000000000' and old['simulation_only']=='false','unexpected original ledger settings')
        require(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]==1 and db.execute('SELECT SUM(charged) FROM attempts').fetchone()[0]==526958000,'retained accounting missing')
        db.execute("UPDATE settings SET value=? WHERE name='limit'",(str(units('12')),))
        db.execute("UPDATE settings SET value=? WHERE name='execution_permit'",(permit.fingerprint,))
        SpendingLedger.audit(db,'reviewed_budget_continuation',{'original_ledger_sha256':before,'previous_limit_usd':'8','new_limit_usd':'12',
            'previous_execution_permit':old['execution_permit'],'new_execution_permit':permit.fingerprint,'review_sha256':digest(review_path),'retained_cost_usd':'0.526958'})
        db.commit()
    finally:db.close()
    ledger=SpendingLedger.open_for_recovery(destination)
    ledger.clear_pause('*',evidence_path=review_path,reason='Explicit author-approved request allowance review; carry forward completed response and original cost; no unknown charges.')
    require(digest(original)==before,'original ledger changed')
    current=ledger.snapshot();require(current['cost']==526958000 and current['held']==0 and not current['pauses'],'carried accounting differs')
    return current

def prepare(destination,guard):
    p=load_plan();workflow_identity();destination,guard=Path(destination),Path(guard)
    require(p.get('budget_amendment_author_approved') is True and os.environ.get('CONFIRM_PAID_GENERATION')=='true','specific budget approval required; no preparation or requests enabled')
    g=load(guard);require(g['batch_id']==BATCH and g['plan_sha256']==digest(PLAN) and g['github_run_id']==os.environ['GITHUB_RUN_ID'] and g['github_commit']==os.environ['GITHUB_SHA'],'review guard differs')
    age=datetime.now(timezone.utc)-datetime.fromisoformat(g['checked_at_utc']);require(timedelta(0)<=age<timedelta(hours=1),'stale guard')
    require(digest(guard.with_suffix('.zip'))==SOURCE_SHA,'original archive differs')
    require(not destination.exists(),'existing continuation state must not be overwritten')
    extract_checked(guard.with_suffix('.zip'),destination/'original')
    original=destination/'original/xai_api_validation';artifact=verify_original(original,p)
    expiry=min(datetime.now(timezone.utc)+timedelta(hours=24),datetime.fromisoformat(p['authorization_valid_until_utc']))
    permission={'schema_version':1,'execution_mode':'live','paid_execution_authorized':True,'cohort':'validation',
        'authorized_by':p['authorized_by'],'authorization_record':p['authorization_record'],'maximum_cost_usd':'12',
        'expires_at_utc':expiry.isoformat(),'snapshot':p['snapshot'],'token_rates':p['token_rates'],'allowed_providers':['xAI'],
        'allowed_artifact_ids':[s['artifact_id'] for s in p['slots']],'driver_sha256':p['driver_sha256']}
    save_json(destination/'execution_permission.json',permission);permit=ExecutionPermit(destination/'execution_permission.json')
    save_json(destination/'budget_review.json',{'author_approved':True,'authorization_record':p['authorization_record'],'previous_limit_usd':'8','maximum_cost_usd':'12',
        'previous_request_allowance_usd':'0.5','new_request_allowance_usd':'1','retained_cost_usd':'0.526958','retained_response':FIRST,'new_response_coordinates':15,
        'original_archive_sha256':SOURCE_SHA,'settings_prompts_oracles_unchanged':True,'invoice_cost_verified':False})
    ledger=migrate_ledger(original/'spending.sqlite',destination/'spending.sqlite',permit,destination/'budget_review.json')
    (destination/'artifacts').mkdir();shutil.copytree(original/'artifacts'/FIRST,destination/'artifacts'/FIRST)
    save_json(destination/'retained_artifact_manifest.json',artifact);save_json(destination/'reviewed_plan.json',p)
    save_json(destination/'run_manifest.json',{'github_run_id':os.environ['GITHUB_RUN_ID'],'github_commit':os.environ['GITHUB_SHA'],'synthetic_data':False,
        'cohort':'validation','excluded_from_main':True,'expected_total_response_coordinates':16,'expected_new_response_coordinates':15,
        'plan_sha256':digest(PLAN),'original_archive_sha256':SOURCE_SHA,'original_ledger_sha256':digest(original/'spending.sqlite')})
    return {'prepared':True,'new_coordinates':15,'retained_coordinates':1,'carried_cost_usd':'0.526958','model_api_calls':0}

def context(destination):
    p=load_plan();workflow_identity();destination=Path(destination);m=load(destination/'run_manifest.json')
    require(p.get('budget_amendment_author_approved') is True and m['plan_sha256']==digest(PLAN) and load(destination/'reviewed_plan.json')==p,'approved stored plan changed')
    require(m['github_run_id']==os.environ['GITHUB_RUN_ID'] and m['github_commit']==os.environ['GITHUB_SHA'],'different workflow state')
    original=destination/'original/xai_api_validation';require(digest(original/'spending.sqlite')==m['original_ledger_sha256'],'original ledger changed')
    retained=verify_original(original,p);config=next(c for c in load(assets_root()/'study.json')['configurations'] if c['id']==p['retained_slot']['configuration_id'])
    require(retained==load(destination/'retained_artifact_manifest.json')==artifact_manifest(destination/'artifacts'/FIRST,p['retained_slot'],config,assets_root()),'retained response changed')
    permit=ExecutionPermit(destination/'execution_permission.json')
    require(permit.document['allowed_artifact_ids']==[s['artifact_id'] for s in p['slots']] and permit.document['allowed_providers']==['xAI'] and permit.document['driver_sha256']==p['driver_sha256'],'continuation permission scope differs')
    ledger=SpendingLedger(destination/'spending.sqlite',limit_usd='12',simulation_only=False,authorization=permit)
    return p,permit,ledger

async def access(destination):
    p,permit,ledger=context(destination)
    async with httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=30) as client:
        r=await client.get('https://api.x.ai/v1/models/grok-4.7',headers={'Authorization':'Bearer '+environment_credential('xAI')})
    require(r.status_code==200 and r.json().get('id')=='grok-4.7','metadata access failed')
    save_json(Path(destination)/'account_access.json',{'passed':True,'http_status':200,'model_id':'grok-4.7','model_generation_calls':0})

async def generate(destination,index):
    p,permit,ledger=context(destination);require(type(index) is int and 0<=index<15,'only15 original unfilled indices allowed')
    slot=p['slots'][index];require(slot['artifact_id']!=FIRST and not (Path(destination)/'artifacts'/slot['artifact_id']).exists(),'response already retained; do not repeat')
    require(load(Path(destination)/'account_access.json')['passed'] is True,'metadata access required')
    class Scoped(LiveGenerator):
        def authorize_slot(self,selected):
            require(selected in p['slots'] and selected['artifact_id']!=FIRST,'outside the15 unfilled validation coordinates')
            super().authorize_slot(selected)
    rates={k:TokenRates(**v) for k,v in p['token_rates'].items()}
    async with Scoped(output=Path(destination)/'artifacts',ledger=ledger,rates=rates,authorization=permit) as generator:
        row=await generator.generate(slot,allowance_usd='1')
    save_json(Path(destination)/f'checkpoint_{index+1:02d}.json',{'artifact_id':slot['artifact_id'],'generation_status':row['generation_status'],'ledger':ledger.snapshot()})
    return {k:row[k] for k in ('artifact_id','generation_status','estimated_token_cost_usd')}

def summarize(destination):
    p,permit,ledger=context(destination);slots=[p['retained_slot'],*p['slots']];configs={c['id']:c for c in load(assets_root()/'study.json')['configurations']}
    require({d.name for d in (Path(destination)/'artifacts').iterdir()}=={s['artifact_id'] for s in slots},'incomplete response allocation')
    rows=[artifact_manifest(Path(destination)/'artifacts'/s['artifact_id'],s,configs[s['configuration_id']],assets_root())['metadata'] for s in slots]
    accounting=ledger.snapshot();require(not accounting['held'] and not accounting['pauses'] and all(a['state']=='settled' for a in accounting['attempts']),'pending financial review')
    out={'complete':True,'retained_response_coordinates':16,'new_response_coordinates':15,'estimated_token_cost_usd':str(Decimal(accounting['cost'])/Decimal(10**9)),
         'invoice_cost_verified':False,'ledger':accounting,'rows':rows,'excluded_from_main':True,'main_outputs':0}
    save_json(Path(destination)/'summary.json',out);return {k:v for k,v in out.items() if k not in ('ledger','rows')}

def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('command',choices=('check-plan','prior-run-check','prepare','access','group','summarize'));a.add_argument('--state',type=Path,required=True);a.add_argument('--guard',type=Path);a.add_argument('--index',type=int);args=a.parse_args()
    try:
        if args.command=='check-plan':p=load_plan();result={'plan_valid':True,'budget_amendment_author_approved':p['budget_amendment_author_approved'],'new_coordinates':15,'model_api_calls':0}
        elif args.command=='prior-run-check':prior_run_check(args.state);result={'guard_verified':True,'model_api_calls':0}
        elif args.command=='prepare':result=prepare(args.state,args.guard)
        elif args.command=='access':asyncio.run(access(args.state));result={'metadata_passed':True,'model_generation_calls':0}
        elif args.command=='group':result=asyncio.run(generate(args.state,args.index))
        else:result=summarize(args.state)
        print(json.dumps(result),flush=True)
    except Exception as exc:
        print(json.dumps({'execution_stopped':True,'error_type':type(exc).__name__,'requires_operator_review':True}),flush=True);raise SystemExit(1) from None
if __name__=='__main__':main()
