"""Continue only the approved first coverage round, preserving all prior outputs.

Six bounded waves add 680 responses to the first forty. Each wave requires the
preceding saved-program evidence audit; model correctness is never a gate.
"""
import argparse, asyncio, json, os, shutil, sqlite3, subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import httpx
from benchmark.expanded.collect import artifact_manifest
from benchmark.expanded.execution_authorization import ExecutionPermit, execution_snapshot
from benchmark.expanded.live_generation import LiveGenerator
from benchmark.expanded.planning import allocation
from benchmark.expanded.providers import TokenRates
from benchmark.expanded.spending import SpendingLedger
from evaluate_saved_openai_validation import extract_checked
from staged_main_first_gate import CAMPAIGN, PROVIDERS, ROOT, identity, load, sha, require, plan as original_plan
from benchmark.expanded.provider_generation import save_json

PLAN=ROOT/'scripts/continue_main_round1_plan.json'
API='repos/agrawal-priyank/depfailbench/'

def slots(provider,wave,root=None):
    require(provider in PROVIDERS and type(wave) is int and 0<=wave<6,'Outside approved round-one continuation')
    lane=[s for s in allocation(root)[0] if s['provider']==provider and s['round']==1]
    return lane[10+60*wave:10+60*(wave+1)]

def prefix(provider,wave,root=None):
    lane=[s for s in allocation(root)[0] if s['provider']==provider and s['round']==1]
    return lane[:min(len(lane),10+60*(wave+1))]

def plan():
    p=load(PLAN);old=original_plan()
    require(p['author_approved'] is True and p['maximum_new_outputs']==680 and p['stop_at_cumulative_main']==720,
            'Coverage scope differs')
    require(p['campaign_namespace']==CAMPAIGN and p['overall_envelope_usd']=='45','Campaign or budget differs')
    require(p['initial_plan_sha256']==sha(ROOT/'scripts/staged_main_first_gate_plan.json'),'Initial plan changed')
    require(all(sha(ROOT/name)==value for name,value in p['orchestration_hashes'].items()),'Continuation orchestration changed')
    require(p['waves']==[{v:[s['artifact_id'] for s in slots(v,w)] for v in PROVIDERS if slots(v,w)} for w in range(6)],'Frozen allocation changed')
    require(sum(len(ids) for wave in p['waves'] for ids in wave.values())==680,'Wrong coverage total')
    return p,old

def get(path):
    return json.loads(subprocess.run(['gh','api',API+path],capture_output=True,check=True).stdout)

def fetch_named(run,commit,name,output):
    require(not output.exists(),'Preserve existing archive')
    found=[a for a in get(f'actions/runs/{run}/artifacts?per_page=100')['artifacts'] if a['name']==name]
    require(len(found)==1 and not found[0]['expired'],'Missing or ambiguous evidence artifact')
    meta=get('actions/artifacts/'+str(found[0]['id']))
    require(meta['workflow_run']['id']==int(run) and meta['workflow_run']['head_sha']==commit,'Evidence run/commit differs')
    output.mkdir(parents=True)
    save_json(output/'metadata.json',meta)
    with (output/'archive.zip').open('xb') as f:
        subprocess.run(['gh','api',API+'actions/artifacts/'+str(meta['id'])+'/zip'],stdout=f,check=True)
    require(meta['digest']=='sha256:'+sha(output/'archive.zip') and meta['size_in_bytes']==(output/'archive.zip').stat().st_size,'Archive digest differs')
    extract_checked(output/'archive.zip',output/'contents')
    return meta

def files(root):
    return {str(f.relative_to(root)):sha(f) for f in root.rglob('*') if f.is_file() and '__pycache__' not in f.parts}

def ledger_rows(path):
    db=sqlite3.connect('file:'+str(path.resolve())+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    result={t:[dict(r) for r in db.execute('select * from '+t+' order by 1')] for t in ['attempts','slots','pauses','settings','audit']}
    db.close();return result

def amend_copy_permission(dbpath,old_permission,new_permission,maximum,source_digest):
    before=ledger_rows(dbpath);settings={r['name']:r['value'] for r in before['settings']}
    require(settings['execution_permit']==sha(old_permission) and settings['simulation_only']=='false' and
            settings['limit']==str(int(Decimal(maximum)*10**9)),'Previous ledger identity/budget differs')
    require(not before['pauses'] and all(r['state']=='settled' and r['charged'] is not None for r in before['attempts']),
            'Unresolved usage or financial pause needs review')
    db=sqlite3.connect(dbpath)
    with db:
        db.execute("update settings set value=? where name='execution_permit'",(sha(new_permission),))
        SpendingLedger.audit(db,'explicit_scoped_continuation',{'previous_permission_sha256':sha(old_permission),
            'new_permission_sha256':sha(new_permission),'prior_archive_sha256':source_digest,
            'authorization':'Author approved continuation from40to720; unchanged cumulative45USD envelope; copied ledger preserves every attempt/charge.'})
    db.close();after=ledger_rows(dbpath)
    require(all(before[t]==after[t] for t in ['attempts','slots','pauses']) and
            before['audit']==after['audit'][:-1],'Prior financial evidence changed')
    return before

def prepare(provider,wave,state):
    p,old=plan();identity()
    require(os.environ.get('CONFIRM_ROUND1_CONTINUATION')=='true' and not state.exists() and slots(provider,wave),'Unapproved or repeated batch')
    if wave==0:
        marker=CAMPAIGN+'-round1-continuation-prepared-'+provider.lower()
        pages=json.loads(subprocess.run(['gh','api','--paginate','--slurp',API+'actions/artifacts?per_page=100&name='+marker],capture_output=True,check=True).stdout)
        require(pages and all(x['total_count']==0 and not x['artifacts'] for x in pages),'Continuation already prepared; preserve and recover without redispatch')
        source=p['initial_evidence'][provider];run=source['run'];commit=source['commit']
        genname=f'fresh-main-first-{run}-{provider.lower()}-final'
        auditname=f'fresh-main-first-audit-{run}-{provider.lower()}-final'
    else:
        run=int(os.environ['GITHUB_RUN_ID']);commit=os.environ['GITHUB_SHA'];source=None
        genname=artifact_name('generation',run,provider,wave-1)
        auditname=artifact_name('audit',run,provider,wave-1)
    prior=state.parent/'prior'/provider.lower()/str(wave)
    gm=fetch_named(run,commit,genname,prior/'generation');am=fetch_named(run,commit,auditname,prior/'audit')
    if source:
        require(gm['id']==source['generation_artifact_id'] and gm['digest']=='sha256:'+source['generation_sha256'] and
                am['id']==source['audit_artifact_id'] and am['digest']=='sha256:'+source['audit_sha256'],'Initial evidence differs from reviewed originals')
    audit=load(prior/'audit/contents/independent_gate_audit.json')
    require(audit['passed'] is True and audit['evidence_complete'] is True and audit['provider']==provider and
            audit['run_id']==run and audit['commit']==commit and audit['campaign_namespace']==CAMPAIGN and
            audit['unresolved_reservations']==0,'Prior evidence has not passed its integrity audit')
    require(audit['main_programs']==(10 if wave==0 else len(slots(provider,wave-1))),'Prior batch scope differs')
    if wave:
        require(audit['wave']==wave-1 and audit['generation_archive_sha256']==sha(prior/'generation/archive.zip'),'Previous wave linkage differs')
    origin=prior/'generation/contents'/provider.lower()
    previous_campaign=origin if wave==0 else origin/'campaign'
    root=previous_campaign/'frozen_repo/expanded_study'
    expected_before=[s for s in prefix(provider,wave,root) if s not in slots(provider,wave,root)]
    require({d.name for d in (previous_campaign/'artifacts').iterdir()}=={s['artifact_id'] for s in expected_before},'Prior campaign prefix is incomplete or extends beyond this wave')
    require(sha(root/'study.json')==sha(ROOT/'expanded_study/study_main_frozen_2026-10-21.json') and
            load(previous_campaign/'reviewed_plan.json')==old,'Frozen scientific protocol changed')
    previous_files=files(previous_campaign)
    shutil.copytree(previous_campaign,state/'campaign');campaign=state/'campaign'
    selected=slots(provider,wave,root);old_permission=campaign/('execution_permission.json' if wave==0 else f'continuation_permissions/wave_{wave-1}.json')
    permission=dict(load(old_permission));permission.update(
        allowed_artifact_ids=[s['artifact_id'] for s in selected],allowed_providers=[provider],
        expires_at_utc=(datetime.now(timezone.utc)+timedelta(hours=48)).isoformat(),
        authorization_record=p['authorization_record'],snapshot=execution_snapshot(campaign/'frozen_repo/expanded_study'))
    new_permission=campaign/f'continuation_permissions/wave_{wave}.json'
    new_permission.parent.mkdir(parents=True,exist_ok=True);save_json(new_permission,permission)
    permit=ExecutionPermit(new_permission,root=campaign/'frozen_repo/expanded_study')
    before=amend_copy_permission(campaign/'spending.sqlite',old_permission,new_permission,
        old['new_campaign_caps_usd'][provider],sha(prior/'generation/archive.zip'))
    require(all(sha(campaign/name)==value for name,value in previous_files.items() if name!='spending.sqlite'),'Copied prior bytes changed')
    save_json(state/'prior_campaign_files.json',previous_files);save_json(state/'prior_ledger_rows.json',before)
    save_json(state/'wave_manifest.json',{'provider':provider,'wave':wave,'slots':selected,
        'campaign_namespace':CAMPAIGN,'run_id':int(os.environ['GITHUB_RUN_ID']),'commit':os.environ['GITHUB_SHA'],
        'plan_sha256':sha(PLAN),'generation_source':gm,'audit_source':am,'previous_programs':len(expected_before),
        'permission_path':str(new_permission.relative_to(campaign)),'expected_cumulative':len(expected_before)+len(selected),
        'source_repairs':0,'synthetic_data':False,'prior_ledger_original_preserved':True})
    SpendingLedger(campaign/'spending.sqlite',limit_usd=old['new_campaign_caps_usd'][provider],simulation_only=False,authorization=permit)
    return {'prepared':True,'new_main_outputs':len(selected),'provider':provider,'wave':wave,'model_api_calls':0}

def context(provider,wave,state):
    p,old=plan();m=load(state/'wave_manifest.json');campaign=state/'campaign';root=campaign/'frozen_repo/expanded_study'
    require(m['provider']==provider and m['wave']==wave and m['slots']==slots(provider,wave,root) and m['plan_sha256']==sha(PLAN),'Prepared wave changed')
    require(m['run_id']==int(os.environ['GITHUB_RUN_ID']) and m['commit']==os.environ['GITHUB_SHA'],'Workflow identity changed')
    identity();require(os.environ.get('CONFIRM_ROUND1_CONTINUATION')=='true','Paid confirmation absent')
    permit=ExecutionPermit(campaign/m['permission_path'],root=root)
    require(permit.document['allowed_artifact_ids']==[s['artifact_id'] for s in m['slots']] and
            permit.document['allowed_providers']==[provider],'Permission exceeds current wave')
    ledger=SpendingLedger(campaign/'spending.sqlite',limit_usd=old['new_campaign_caps_usd'][provider],simulation_only=False,authorization=permit)
    return p,old,m,campaign,root,permit,ledger

async def generate(provider,wave,state):
    _,old,m,campaign,root,permit,ledger=context(provider,wave,state)
    require(not (state/'generation_started.json').exists(),'An accepted or interrupted wave must not be rerun')
    save_json(state/'generation_started.json',{'run_id':m['run_id'],'wave':wave})
    def credential(requested):
        require(requested==provider,'Wrong credential scope');value=os.environ.get('ROUND1_PROVIDER_API_KEY')
        require(isinstance(value,str) and value and not any(c in value for c in '\r\n'),'Missing provider secret')
        return value
    selected=[]
    class Scoped(LiveGenerator):
        def authorize_slot(self,s):
            require(s in selected and s in m['slots'],'Outside the current fixed pair')
            super().authorize_slot(s)
    rates={name:TokenRates(**v) for name,v in old['token_rates'].items()}
    async with Scoped(output=campaign/'artifacts',ledger=ledger,rates=rates,authorization=permit,root=root,credential_loader=credential) as sender:
        for index in range(0,len(m['slots']),2):
            selected[:]=m['slots'][index:index+2]
            require(all(not(campaign/'artifacts'/s['artifact_id']).exists() for s in selected),'Never replace a saved attempt/output')
            results=await asyncio.gather(*(sender.generate(s,allowance_usd=old['per_request_allowance_usd'][s['model_id']]) for s in selected),return_exceptions=True)
            require(not any(isinstance(r,BaseException) for r in results),'Generation paused; preserve all attempts and review')
            print(json.dumps({'provider':provider,'wave':wave,'completed_new':index+len(selected),'batch_total':len(m['slots'])}),flush=True)
    return summarize(provider,wave,state)

def summarize(provider,wave,state):
    _,_,m,campaign,root,permit,ledger=context(provider,wave,state)
    require({d.name for d in (campaign/'artifacts').iterdir()}=={s['artifact_id'] for s in prefix(provider,wave,root)},'Missing or extra cumulative outputs')
    configs={c['id']:c for c in load(root/'study.json')['configurations']}
    for s in prefix(provider,wave,root):
        require(not artifact_manifest(campaign/'artifacts'/s['artifact_id'],s,configs[s['configuration_id']],root)['synthetic_data'],'Synthetic output in main evidence')
    require(all(sha(campaign/name)==value for name,value in load(state/'prior_campaign_files.json').items() if name!='spending.sqlite'),'Prior outputs changed')
    budget=ledger.snapshot();require(not budget['held'] and not budget['pauses'] and all(a['state']=='settled' for a in budget['attempts']),'Unresolved usage or spending pause')
    report={'complete':True,'provider':provider,'wave':wave,'programs':len(m['slots']),'cumulative_programs':m['expected_cumulative'],
        'estimated_cumulative_token_cost_usd':str(Decimal(budget['cost'])/Decimal(10**9)),
        'invoice_cost_verified':False,'ledger':budget,'minimum_model_pass_rate':None,'source_repairs':0}
    save_json(state/'generation_summary.json',report);return {k:v for k,v in report.items() if k!='ledger'}

def artifact_name(kind,run,provider,wave):
    require(kind in {'generation','evaluation','audit'} and provider in PROVIDERS and type(wave) is int and 0<=wave<6,'Invalid artifact scope')
    return f'fresh-main-round1-{kind}-{run}-w{wave}-{provider.lower()}-final'

if __name__=='__main__':
    q=argparse.ArgumentParser(description=__doc__);q.add_argument('mode',choices=['check','prepare','generate'])
    q.add_argument('--provider',choices=PROVIDERS);q.add_argument('--wave',type=int);q.add_argument('--state',type=Path);a=q.parse_args()
    try:
        if a.mode=='check':plan();report={'passed':True,'maximum_new_main_outputs':680,'model_api_calls':0}
        elif a.mode=='prepare':report=prepare(a.provider,a.wave,a.state)
        else:report=asyncio.run(generate(a.provider,a.wave,a.state))
        print(json.dumps(report),flush=True)
    except Exception as e:
        print(json.dumps({'stopped':True,'error_type':type(e).__name__,'requires_review':True}),flush=True)
        raise SystemExit(1) from None
