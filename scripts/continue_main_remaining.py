"""Bounded, audited rounds2–6 of the frozen main cohort; stop at4320."""
import argparse, asyncio, json, os, shutil, sqlite3, subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from functools import lru_cache
from benchmark.expanded.collect import artifact_manifest
from benchmark.expanded.execution_authorization import ExecutionPermit, execution_snapshot
from benchmark.expanded.live_generation import LiveGenerator
from benchmark.expanded.planning import allocation, assets_root
from benchmark.expanded.providers import TokenRates
from benchmark.expanded.spending import SpendingLedger
from benchmark.expanded.provider_generation import save_json
from continue_main_round1 import fetch_named, files, ledger_rows
from staged_main_first_gate import CAMPAIGN, PROVIDERS, ROOT, load, sha, require

PLAN=ROOT/'scripts/continue_main_remaining_plan.json'
API='repos/agrawal-priyank/depfailbench/'


def round_number():
    value=os.environ.get('REMAINING_ROUND','2')
    require(value in ['2','3','4','5','6'],'Outside approved remaining rounds')
    return int(value)


@lru_cache(maxsize=8)
def _schedule(root_name, asset_hashes):
    return allocation(Path(root_name))[0]


def schedule(root=None):
    root=assets_root(root)
    # Cache only unchanged allocation inputs; asset mutation gets a new key.
    key=tuple((str(f.relative_to(root)),sha(f)) for f in [root/'study.json',*sorted((root/'prompts').glob('*.md'))])
    return _schedule(str(root.resolve()),key)


def slots(provider,wave,root=None,round_id=None):
    r=round_number() if round_id is None else round_id
    require(provider in PROVIDERS and type(wave) is int and 0<=wave<6 and type(r) is int and 2<=r<=6,'Outside remaining scope')
    lane=[s for s in schedule(root) if s['provider']==provider and s['round']==r]
    return lane[60*wave:60*(wave+1)]


def prefix(provider,wave,root=None,round_id=None):
    r=round_number() if round_id is None else round_id
    chosen=slots(provider,wave,root,r)
    require(chosen,'Empty provider wave')
    return [s for s in schedule(root) if s['provider']==provider and
            (s['round']<r or s['round']==r and s['sequence']<=chosen[-1]['sequence'])]


def last_wave(provider):
    return {'Anthropic':1,'OpenAI':5,'Google':1,'Mistral':3}[provider]


def plan():
    p=load(PLAN);old=load(ROOT/'scripts/staged_main_first_gate_plan.json')
    require(p['author_approved'] is True and p['maximum_new_outputs']==3600 and p['stop_at_cumulative_main']==4320,'Unapproved remaining scope')
    require(p['campaign_namespace']==CAMPAIGN and p['overall_envelope_usd']=='45' and
            p['maximum_inflight_per_provider']==2 and p['maximum_new_outputs_per_provider_batch']==60 and p['evaluation_shards']==4,'Execution bounds changed')
    require(sha(ROOT/'scripts/staged_main_first_gate_plan.json')==p['initial_plan_sha256'],'Original financial plan changed')
    require(old['new_campaign_caps_usd']==p['new_campaign_caps_usd'],'Existing provider caps changed')
    for name,value in {**p['unchanged_scientific_files'],**p['orchestration_hashes']}.items():
        require(sha(ROOT/name)==value,'Reviewed source changed: '+name)
    require(p['rounds']=={str(r):[{v:[s['artifact_id'] for s in slots(v,w,round_id=r)]
            for v in PROVIDERS if slots(v,w,round_id=r)} for w in range(6)] for r in range(2,7)},'Fixed allocation changed')
    require(sum(len(ids) for waves in p['rounds'].values() for wave in waves for ids in wave.values())==3600,'Wrong remaining total')
    return p,old


def identity():
    p,_=plan()
    require(os.environ.get('GITHUB_REPOSITORY')=='agrawal-priyank/depfailbench' and
            os.environ.get('GITHUB_REF')=='refs/heads/'+p['branch'] and os.environ.get('GITHUB_RUN_ATTEMPT')=='1' and
            os.environ.get('GITHUB_RUN_ID') and os.environ.get('GITHUB_SHA'),'Approved original workflow required')
    round_number()


def artifact_name(kind,run,provider,wave,round_id=None,shard=None):
    r=round_number() if round_id is None else round_id
    slots(provider,wave,round_id=r)
    require(kind in ['generation','evaluation','audit'],'Wrong artifact kind')
    suffix=''
    if kind=='evaluation':
        require(type(shard) is int and 0<=shard<4,'Invalid evaluation partition');suffix=f'-s{shard}'
    return f'fresh-main-remaining-{kind}-{run}-r{r}-w{wave}-{provider.lower()}{suffix}-final'


def get(path):
    return json.loads(subprocess.run(['gh','api',API+path],capture_output=True,check=True).stdout)


def amend_copy_permission(dbpath,old_permission,new_permission,maximum,source_digest):
    before=ledger_rows(dbpath);settings={r['name']:r['value'] for r in before['settings']}
    require(settings['execution_permit']==sha(old_permission) and settings['simulation_only']=='false' and
            settings['limit']==str(int(Decimal(maximum)*10**9)),'Ledger identity or existing cap differs')
    require(not before['pauses'] and all(r['state']=='settled' and r['charged'] is not None for r in before['attempts']),
            'Unresolved usage or financial pause; preserve and review')
    db=sqlite3.connect(dbpath)
    with db:
        db.execute("update settings set value=? where name='execution_permit'",(sha(new_permission),))
        SpendingLedger.audit(db,'explicit_scoped_continuation',{'previous_permission_sha256':sha(old_permission),
            'new_permission_sha256':sha(new_permission),'prior_archive_sha256':source_digest,
            'authorization':'Author approved remaining3600 after corrected720 review; unchanged cumulative45USD envelope and original caps; preserve every prior attempt and charge.'})
    db.close();after=ledger_rows(dbpath)
    require(all(before[t]==after[t] for t in ['attempts','slots','pauses']) and before['audit']==after['audit'][:-1],'Prior financial evidence changed')
    return before


def prepare_from_saved(provider,wave,state,prior,gm,am):
    p,old=plan();r=round_number();identity()
    require(os.environ.get('CONFIRM_REMAINING_MAIN')=='true' and not state.exists() and slots(provider,wave),'Unapproved or repeated batch')
    audit=load(prior/'audit/contents/independent_gate_audit.json') if (r,wave)!=(2,0) else load(prior/'audit/contents/independent_review_audit.json')
    require(audit['passed'] is True,'Prior integrity audit failed')
    if (r,wave)==(2,0):
        require(audit['outputs']==720 and audit['records']==6480 and audit['new_generated_outputs']==0 and
                audit['reevaluation_run_id']==p['initial_corrected_audit']['run_id'] and
                audit['reevaluation_commit']==p['initial_corrected_audit']['commit'],'Corrected720 proof differs')
    else:
        previous_round=r if wave else r-1;previous_wave=wave-1 if wave else last_wave(provider)
        require(audit['evidence_complete'] and audit['provider']==provider and audit['round']==previous_round and
                audit['wave']==previous_wave and audit['run_id']==gm['workflow_run']['id'] and
                audit['commit']==gm['workflow_run']['head_sha']==am['workflow_run']['head_sha'] and
                audit['run_id']==am['workflow_run']['id'] and audit['campaign_namespace']==CAMPAIGN and
                audit['main_programs']==len(slots(provider,previous_wave,round_id=previous_round)) and
                audit['records']==9*audit['main_programs'] and audit['unresolved_reservations']==0 and
                audit['generation_archive_sha256']==sha(prior/'generation/archive.zip'),'Prior provider audit/source link differs')
    previous_campaign=prior/'generation/contents'/provider.lower()/'campaign'
    root=previous_campaign/'frozen_repo/expanded_study';expected_before=[s for s in prefix(provider,wave,root) if s not in slots(provider,wave,root)]
    require({f.name for f in (previous_campaign/'artifacts').iterdir()}=={s['artifact_id'] for s in expected_before},'Prior provider prefix incomplete or excessive')
    require(sha(root/'study.json')==p['frozen_study_sha256'] and load(previous_campaign/'reviewed_plan.json')==old,'Frozen study or financial plan changed')
    previous_files=files(previous_campaign);shutil.copytree(previous_campaign,state/'campaign');campaign=state/'campaign'
    if wave:old_permission=campaign/f'remaining_permissions/r{r}_w{wave-1}.json'
    elif r>2:old_permission=campaign/f'remaining_permissions/r{r-1}_w{last_wave(provider)}.json'
    else:old_permission=campaign/f'continuation_permissions/wave_{p["initial_sources"][provider]["last_wave"]}.json'
    permission=dict(load(old_permission));permission.update(allowed_artifact_ids=[s['artifact_id'] for s in slots(provider,wave,root)],
        allowed_providers=[provider],expires_at_utc=(datetime.now(timezone.utc)+timedelta(hours=48)).isoformat(),
        authorization_record=p['authorization_record'],snapshot=execution_snapshot(root))
    new_permission=campaign/f'remaining_permissions/r{r}_w{wave}.json';new_permission.parent.mkdir(parents=True,exist_ok=True);save_json(new_permission,permission)
    permit=ExecutionPermit(new_permission,root=root)
    before=amend_copy_permission(campaign/'spending.sqlite',old_permission,new_permission,old['new_campaign_caps_usd'][provider],sha(prior/'generation/archive.zip'))
    require(all(sha(campaign/name)==h for name,h in previous_files.items() if name!='spending.sqlite'),'Copied prior bytes changed')
    save_json(state/'prior_campaign_files.json',previous_files);save_json(state/'prior_ledger_rows.json',before)
    save_json(state/'wave_manifest.json',{'provider':provider,'round':r,'wave':wave,'slots':slots(provider,wave,root),
        'campaign_namespace':CAMPAIGN,'run_id':int(os.environ['GITHUB_RUN_ID']),'commit':os.environ['GITHUB_SHA'],
        'plan_sha256':sha(PLAN),'generation_source':gm,'audit_source':am,'previous_programs':len(expected_before),
        'permission_path':str(new_permission.relative_to(campaign)),'expected_cumulative':len(prefix(provider,wave,root)),
        'source_repairs':0,'synthetic_data':False,'prior_ledger_original_preserved':True})
    SpendingLedger(campaign/'spending.sqlite',limit_usd=old['new_campaign_caps_usd'][provider],simulation_only=False,authorization=permit)
    return {'prepared':True,'provider':provider,'round':r,'wave':wave,'new_outputs':len(slots(provider,wave)),'model_api_calls':0}


def prepare(provider,wave,state):
    p,_=plan();identity();r=round_number()
    require(os.environ.get('CONFIRM_REMAINING_MAIN')=='true' and not state.exists() and slots(provider,wave),'Unapproved or repeated batch')
    if wave==0:
        marker=CAMPAIGN+f'-remaining-r{r}-prepared-'+provider.lower()
        pages=json.loads(subprocess.run(['gh','api','--paginate','--slurp',API+'actions/artifacts?per_page=100&name='+marker],capture_output=True,check=True).stdout)
        require(pages and all(x['total_count']==0 and not x['artifacts'] for x in pages),'Round already prepared; never redispatch blindly')
    prior=state.parent.parent/'prior'/provider.lower()/f'r{r}_w{wave}'
    if (r,wave)==(2,0):
        source=p['initial_sources'][provider];a=p['initial_corrected_audit']
        gm=fetch_named(source['run_id'],source['commit'],source['artifact_name'],prior/'generation')
        am=fetch_named(a['run_id'],a['commit'],a['artifact_name'],prior/'audit')
        require(gm['id']==source['artifact_id'] and gm['digest']=='sha256:'+source['archive_sha256'] and
                am['id']==a['artifact_id'] and am['digest']=='sha256:'+a['archive_sha256'],'Initial exact evidence differs')
    else:
        previous_round=r if wave else r-1;previous_wave=wave-1 if wave else last_wave(provider)
        run=int(os.environ['GITHUB_RUN_ID']) if wave else int(os.environ['PREVIOUS_ROUND_RUN'])
        require(run!=int(os.environ['GITHUB_RUN_ID']) if not wave else True,'Previous round must have a distinct run')
        gm=fetch_named(run,os.environ['GITHUB_SHA'],artifact_name('generation',run,provider,previous_wave,previous_round),prior/'generation')
        am=fetch_named(run,os.environ['GITHUB_SHA'],artifact_name('audit',run,provider,previous_wave,previous_round),prior/'audit')
        if not wave:
            completion=fetch_named(run,os.environ['GITHUB_SHA'],f'remaining-main-completion-{run}',prior/'round_completion')
            completed=load(prior/'round_completion/contents/round_completion.json')
            require(completed['passed'] and completed['round']==r-1 and completed['new_outputs']==720 and
                    completed['records']==6480 and completed['groups']==14,'Previous round incomplete')
    return prepare_from_saved(provider,wave,state,prior,gm,am)


def context(provider,wave,state):
    p,old=plan();identity();require(os.environ.get('CONFIRM_REMAINING_MAIN')=='true','Paid confirmation absent')
    m=load(state/'wave_manifest.json');campaign=state/'campaign';root=campaign/'frozen_repo/expanded_study'
    require(m['provider']==provider and m['round']==round_number() and m['wave']==wave and
            m['slots']==slots(provider,wave,root) and m['plan_sha256']==sha(PLAN) and
            m['run_id']==int(os.environ['GITHUB_RUN_ID']) and m['commit']==os.environ['GITHUB_SHA'],'Prepared identity or scope changed')
    permit=ExecutionPermit(campaign/m['permission_path'],root=root)
    require(permit.document['allowed_providers']==[provider] and permit.document['allowed_artifact_ids']==[s['artifact_id'] for s in m['slots']],'Permission exceeds current batch')
    ledger=SpendingLedger(campaign/'spending.sqlite',limit_usd=old['new_campaign_caps_usd'][provider],simulation_only=False,authorization=permit)
    return p,old,m,campaign,root,permit,ledger


async def generate(provider,wave,state):
    _,old,m,campaign,root,permit,ledger=context(provider,wave,state)
    require(not(state/'generation_started.json').exists(),'Never rerun accepted or interrupted calls')
    save_json(state/'generation_started.json',{'run_id':m['run_id'],'round':m['round'],'wave':wave})
    def credential(requested):
        require(requested==provider,'Wrong credential scope');value=os.environ.get('REMAINING_PROVIDER_API_KEY')
        require(isinstance(value,str) and value and not any(c in value for c in '\r\n'),'Provider credential missing or invalid')
        return value
    selected=[]
    class Scoped(LiveGenerator):
        def authorize_slot(self,s):
            require(s in selected and s in m['slots'],'Outside current fixed pair');super().authorize_slot(s)
    rates={name:TokenRates(**v) for name,v in old['token_rates'].items()}
    async with Scoped(output=campaign/'artifacts',ledger=ledger,rates=rates,authorization=permit,root=root,credential_loader=credential) as sender:
        for index in range(0,len(m['slots']),2):
            selected[:]=m['slots'][index:index+2]
            require(all(not(campaign/'artifacts'/s['artifact_id']).exists() for s in selected),'Never replace any attempt or output')
            results=await asyncio.gather(*(sender.generate(s,allowance_usd=old['per_request_allowance_usd'][s['model_id']]) for s in selected),return_exceptions=True)
            require(not any(isinstance(v,BaseException) for v in results),'Generation paused; preserve and review all attempts')
            print(json.dumps({'provider':provider,'round':m['round'],'wave':wave,'completed_new':index+len(selected),'batch_total':len(m['slots'])}),flush=True)
    return summarize(provider,wave,state)


def summarize(provider,wave,state):
    _,_,m,campaign,root,permit,ledger=context(provider,wave,state)
    require({d.name for d in (campaign/'artifacts').iterdir()}=={s['artifact_id'] for s in prefix(provider,wave,root)},'Cumulative sources missing or excessive')
    configs={c['id']:c for c in load(root/'study.json')['configurations']}
    for slot in prefix(provider,wave,root):require(not artifact_manifest(campaign/'artifacts'/slot['artifact_id'],slot,configs[slot['configuration_id']],root)['synthetic_data'],'Synthetic source in main study')
    require(all(sha(campaign/name)==h for name,h in load(state/'prior_campaign_files.json').items() if name!='spending.sqlite'),'Prior bytes changed')
    budget=ledger.snapshot();require(not budget['held'] and not budget['pauses'] and all(a['state']=='settled' for a in budget['attempts']),'Unresolved usage or spending pause')
    report={'complete':True,'provider':provider,'round':m['round'],'wave':wave,'programs':len(m['slots']),
        'cumulative_programs':m['expected_cumulative'],'estimated_cumulative_token_cost_usd':str(Decimal(budget['cost'])/Decimal(10**9)),
        'invoice_cost_verified':False,'ledger':budget,'minimum_model_pass_rate':None,'source_repairs':0}
    save_json(state/'generation_summary.json',report);return {k:v for k,v in report.items() if k!='ledger'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['check','prepare','generate'])
    parser.add_argument('--provider',choices=PROVIDERS);parser.add_argument('--wave',type=int);parser.add_argument('--state',type=Path);a=parser.parse_args()
    if a.mode=='check':plan();out={'passed':True,'maximum_new_outputs':3600,'model_api_calls':0}
    elif a.mode=='prepare':out=prepare(a.provider,a.wave,a.state)
    else:out=asyncio.run(generate(a.provider,a.wave,a.state))
    print(json.dumps(out),flush=True)
