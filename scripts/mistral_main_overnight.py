"""Continue only the frozen Mistral main allocation, preserving its first ten."""
import argparse,asyncio,hashlib,json,os,shutil,sqlite3,subprocess
from pathlib import Path
from datetime import datetime,timezone
from benchmark.expanded.execution_authorization import ExecutionPermit,execution_snapshot
from benchmark.expanded.live_generation import LiveGenerator
from benchmark.expanded.planning import allocation,assets_root
from benchmark.expanded.provider_generation import save_json
from benchmark.expanded.providers import TokenRates
from benchmark.expanded.spending import DispatchPaused,SpendingLedger,units
from evaluate_saved_openai_validation import extract_checked
ROOT=Path(__file__).resolve().parents[1];PLAN=ROOT/'scripts/mistral_main_overnight_plan.json'
MARKER='array-main-mistral-overnight-20261020-v1-prepared'
SOURCE_SHA='4f2ca77a1d45b082e3a5a285d068385a410127c7b3ede2b6e194c403a8b2706a'
def load(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(ok,message):
    if not ok:raise DispatchPaused(message)
def load_plan():
    p=load(PLAN);require(p['author_approved'] is True and p['maximum_cost_usd']=='2.00' and p['overall_main_allowance_usd']=='45','approval/allowance differs')
    require(p['snapshot']==execution_snapshot() and p['driver_sha256']==sha(Path(__file__)),'core or driver differs')
    require(p['source_archive_sha256']==SOURCE_SHA,'wrong original main archive')
    require(p['mistral_slots']==[s for s in allocation()[0] if s['provider']=='Mistral'] and len(p['mistral_slots'])==1440,'allocation differs')
    require(p['mistral_slots'][:10]==allocation()[0][:10] and p['wave_size']==40 and p['waves']==36,'frozen prefix/waves differ')
    return p
def identity():
    require(os.environ.get('GITHUB_REPOSITORY')=='agrawal-priyank/depfailbench' and os.environ.get('GITHUB_RUN_ATTEMPT')=='1' and os.environ.get('GITHUB_REF')=='refs/heads/array-revision-linux-validation' and os.environ.get('GITHUB_RUN_ID') and os.environ.get('GITHUB_SHA'),'original revision workflow required')
def prior(path):
    load_plan();identity();require(not path.exists(),'guard exists')
    r=subprocess.run(['gh','api','--paginate','--slurp','repos/agrawal-priyank/depfailbench/actions/artifacts?per_page=100&name='+MARKER],text=True,capture_output=True);require(r.returncode==0,'artifact inventory unavailable');pages=json.loads(r.stdout);require(bool(pages) and all(p['total_count']==0 and not p['artifacts'] for p in pages),'campaign already prepared; recover without redispatch')
    path.parent.mkdir(parents=True,exist_ok=True);save_json(path,{'clear':True,'run':os.environ['GITHUB_RUN_ID'],'commit':os.environ['GITHUB_SHA'],'plan_sha256':sha(PLAN),'at':datetime.now(timezone.utc).isoformat()})
def prepare(state,archive,*,guard=None,mock=False):
    p=load_plan();require(not state.exists(),'existing campaign must be preserved')
    if not mock:
        identity();require(os.environ.get('CONFIRM_MISTRAL_OVERNIGHT')=='true','explicit confirmation missing');require(sha(archive)==SOURCE_SHA,'wrong first-main archive')
        require(guard is not None and guard.is_file(),'prior guard missing');g=load(guard);require(g['clear'] and g['run']==os.environ['GITHUB_RUN_ID'] and g['commit']==os.environ['GITHUB_SHA'] and g['plan_sha256']==sha(PLAN) and 0<=(datetime.now(timezone.utc)-datetime.fromisoformat(g['at'])).total_seconds()<=3600,'wrong/expired guard')
    extract_checked(archive,state/'original_first_block');original=state/'original_first_block/main_mistral_first_block'
    old_manifest=load(original/'main_batch_manifest.json');require(old_manifest['slots']==p['mistral_slots'][:10] and old_manifest['synthetic_data'] is mock,'first-block identities/provenance differ')
    shutil.copytree(original,state/'campaign');c=state/'campaign';root=c/'frozen_repo/expanded_study';old_permission=load(c/'execution_permission.json')
    require(old_permission['maximum_cost_usd']=='1.00' and old_permission['allowed_providers']==['Mistral'] and old_permission['snapshot']==execution_snapshot(root),'original permission differs')
    require(old_permission['allowed_artifact_ids']==[s['artifact_id'] for s in p['mistral_slots']],'Mistral permission scope differs')
    require({d.name for d in (c/'artifacts').iterdir()}=={s['artifact_id'] for s in p['mistral_slots'][:10]},'original first ten incomplete or unexpected')
    for s in p['mistral_slots'][:10]:require(load(c/'artifacts'/s['artifact_id']/'metadata.json')['synthetic_data'] is mock,'source provenance differs')
    old_bytes=(c/'execution_permission.json').read_bytes();new=json.loads(json.dumps(old_permission));new['maximum_cost_usd']='2.00';new['authorization_record']=p['authorization_record'];new['execution_mode']='mock_validation' if mock else 'live';new['paid_execution_authorized']=not mock;new['mock_validation_authorized']=mock
    save_json(c/'previous_execution_permission.json',old_permission);save_json(c/'overnight_execution_permission.json',new);permit=ExecutionPermit(c/'overnight_execution_permission.json',root=root)
    # Explicitly amend the reviewed COPY. All old attempt/slot/hold rows remain.
    db=sqlite3.connect(c/'spending.sqlite');db.row_factory=sqlite3.Row
    before={t:[dict(r) for r in db.execute('select * from '+t)] for t in ['attempts','slots','pauses']};settings=dict(db.execute('select name,value from settings'))
    require(settings['limit']==str(units('1.00')) and settings['execution_permit']==hashlib.sha256(old_bytes).hexdigest(),'original ledger permission mismatch')
    require(len(before['attempts'])==10 and all(a['state']=='settled' and a['charged'] is not None for a in before['attempts']) and not before['pauses'],'unresolved original charges require review')
    if not mock:require(sum(a['charged'] for a in before['attempts'])==units('0.0018806'),'original spent amount differs')
    db.execute('update settings set value=? where name=?',(str(units('2.00')),'limit'));db.execute('update settings set value=? where name=?',(permit.fingerprint,'execution_permit'))
    details={'author':'Priyank Agrawal','reason':'Author confirmed$20 Mistral balance and permitted increased allowance; reviewed overnight cap$2 within$45 overall.','old_limit_usd':'1.00','new_limit_usd':'2.00','source_archive_sha256':sha(archive),'old_permission_sha256':hashlib.sha256(old_bytes).hexdigest(),'new_permission_sha256':permit.fingerprint,'prior_costs_and_holds_preserved':True}
    db.execute('insert into audit(utc,event,details) values(?,?,?)',(datetime.now(timezone.utc).isoformat(),'explicit_author_budget_amendment',json.dumps(details,sort_keys=True)));db.commit()
    require(before=={t:[dict(r) for r in db.execute('select * from '+t)] for t in before},'budget amendment changed attempts/slots/pauses');db.close()
    SpendingLedger(c/'spending.sqlite',limit_usd='2.00',simulation_only=False,authorization=permit)
    save_json(state/'budget_amendment.json',details);save_json(state/'reviewed_plan.json',p)
    save_json(state/'campaign_manifest.json',{'github_run_id':os.environ.get('GITHUB_RUN_ID'),'github_commit':os.environ.get('GITHUB_SHA'),'synthetic_data':mock,'driver_sha256':p['driver_sha256'],'source_archive_sha256':sha(archive),'already_retained':10,'new_responses':1430,'total_mistral':1440,'total_main':4320,'other_families_paused':True,'original_files':{str(f.relative_to(state/'original_first_block')):sha(f) for f in (state/'original_first_block').rglob('*') if f.is_file()}})
    return {'prepared':True,'retained_main':10,'unfilled_mistral':1430,'model_api_calls':0}
def wave_slots(p,index):
    require(type(index) is int and index in range(36),'outside reviewed waves');return p['mistral_slots'][10+index*40:10+(index+1)*40]
async def generate_wave(state,index,*,mock_transport=None,mock_credential=None):
    p=load_plan();slots=wave_slots(p,index);m=load(state/'campaign_manifest.json')
    if m['synthetic_data']:
        import httpx
        require(type(mock_transport) is httpx.MockTransport and callable(mock_credential),'mock transport/credential required')
    else:
        identity();require(os.environ.get('CONFIRM_MISTRAL_OVERNIGHT')=='true' and m['github_run_id']==os.environ['GITHUB_RUN_ID'] and m['github_commit']==os.environ['GITHUB_SHA'],'wrong campaign confirmation/identity');require(mock_transport is None and mock_credential is None,'live campaign cannot substitute mocks')
    require(m['driver_sha256']==p['driver_sha256'],'driver changed');c=state/'campaign';root=c/'frozen_repo/expanded_study'
    prefix=p['mistral_slots'][:10+index*40];require({x.name for x in (c/'artifacts').iterdir()}=={s['artifact_id'] for s in prefix},'existing partial wave or missing preceding outputs; inspect without rerun')
    if index:require((state/f'wave_{index-1}_summary.json').is_file(),'preceding wave not complete')
    permit=ExecutionPermit(c/'overnight_execution_permission.json',root=root);require(permit.document['allowed_providers']==['Mistral'] and permit.document['allowed_artifact_ids']==[s['artifact_id'] for s in p['mistral_slots']],'permission outside Mistral')
    allowed={s['artifact_id']:s for s in slots}
    class Scoped(LiveGenerator):
        def authorize_slot(self,value):
            require(allowed.get(value['artifact_id'])==value and value['provider']=='Mistral' and value['cohort']=='main','outside this frozen main wave');super().authorize_slot(value)
    ledger=SpendingLedger(c/'spending.sqlite',limit_usd='2.00',simulation_only=False,authorization=permit);rates={k:TokenRates(**v) for k,v in p['token_rates'].items()};options={'wire_transport':mock_transport,'credential_loader':mock_credential} if m['synthetic_data'] else {};rows=[]
    try:
        async with Scoped(output=c/'artifacts',ledger=ledger,rates=rates,authorization=permit,root=root,**options) as sender:
            # Ordered pairs respect the frozen provider subsequence, at most two in flight.
            for offset in range(0,len(slots),2):
                outcomes=await asyncio.gather(*(sender.generate(s,allowance_usd='0.02') for s in slots[offset:offset+2]),return_exceptions=True)
                for s,result in zip(slots[offset:offset+2],outcomes):
                    if isinstance(result,BaseException):continue
                    rows.append({'artifact_id':s['artifact_id'],'generation_status':result['generation_status'],'estimated_token_cost_usd':result['estimated_token_cost_usd']})
                failures=[r for r in outcomes if isinstance(r,BaseException)]
                if failures:raise failures[0]
        require(len(rows)==len(slots),'wave incomplete');save_json(state/f'wave_{index}_summary.json',{'index':index,'new_main_responses':len(rows),'retained_main_responses':10+index*40+len(rows),'rows':rows,'functional_tests_performed':False})
        return {'wave':index,'new_main_responses':len(rows),'mistral_main_total_so_far':10+index*40+len(rows)}
    finally:
        # Delta packaging is outside campaign so final evidence does not recursively duplicate it.
        pack=state.parent/'mistral_wave_checkpoints'/f'wave_{index}';require(not pack.exists(),'checkpoint package exists');pack.mkdir(parents=True)
        for s in slots:
            source=c/'artifacts'/s['artifact_id']
            if source.exists():shutil.copytree(source,pack/'artifacts'/s['artifact_id'])
        shutil.copyfile(c/'spending.sqlite',pack/'spending.sqlite');shutil.copyfile(c/'overnight_execution_permission.json',pack/'execution_permission.json');save_json(pack/'wave_preservation.json',{'wave':index,'attempted_artifact_ids':[x.name for x in (pack/'artifacts').iterdir()] if (pack/'artifacts').exists() else [],'complete_summary_present':(state/f'wave_{index}_summary.json').exists(),'all_original_attempt_bytes_preserved':True})
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prior-run-check','prepare','wave']);p.add_argument('--state',type=Path,required=True);p.add_argument('--archive',type=Path);p.add_argument('--guard',type=Path);p.add_argument('--index',type=int);a=p.parse_args()
    try:
        if a.mode=='prior-run-check':prior(a.state);r={'prior_clear':True}
        elif a.mode=='prepare':r=prepare(a.state,a.archive,guard=a.guard)
        else:r=asyncio.run(generate_wave(a.state,a.index))
        print(json.dumps(r),flush=True)
    except Exception as exc:print(json.dumps({'stopped':True,'error_type':type(exc).__name__,'requires_review':True}),flush=True);raise SystemExit(1) from None
