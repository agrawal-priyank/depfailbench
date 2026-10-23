"""Exact-commit software entry gate and bounded cloud round advancement."""
import argparse,json,os,subprocess
from pathlib import Path
from decimal import Decimal
from datetime import datetime,timezone
import xml.etree.ElementTree as ET
from continue_main_remaining import PLAN,API,CAMPAIGN,PROVIDERS,plan,identity,round_number,slots,last_wave,artifact_name,fetch_named,load,sha,require,get
from evaluate_main_remaining import save


def software_report(output):
    identity();p,_=plan();tree=ET.parse(output/'software.xml');suites=[e for e in tree.getroot().iter('testsuite')]
    require(sum(int(e.get('tests','0')) for e in suites)==p['expected_software_tests'] and
        not any(int(e.get(k,'0')) for e in suites for k in ['errors','failures','skipped']),'Software suite incomplete or failed')
    save(output/'software_gate.json',{'passed':True,'tests':p['expected_software_tests'],'commit':os.environ['GITHUB_SHA'],
        'run_id':int(os.environ['GITHUB_RUN_ID']),'attempt':1,'mode':os.environ['REMAINING_MODE'],'plan_sha256':sha(PLAN),'model_api_calls':0})


def entry(output):
    identity();p,_=plan();r=round_number();require(os.environ['REMAINING_MODE']=='paid','Not a paid entry')
    verified=int(os.environ['VERIFIED_SOFTWARE_RUN']);run=get(f'actions/runs/{verified}')
    require(run['status']=='completed' and run['conclusion']=='success' and run['run_attempt']==1 and
        run['head_sha']==os.environ['GITHUB_SHA'] and run['head_branch']==p['branch'] and run['workflow_id']==p['workflow_id'],'Exact-commit software gate not successful')
    fetch_named(verified,os.environ['GITHUB_SHA'],f'remaining-main-software-{verified}',output/'software')
    proof=load(output/'software/contents/software_gate.json')
    require(proof=={'passed':True,'tests':p['expected_software_tests'],'commit':os.environ['GITHUB_SHA'],
        'run_id':verified,'attempt':1,'mode':'software','plan_sha256':sha(PLAN),'model_api_calls':0},'Wrong software gate proof')
    if r==4:
        require(os.environ.get('PREVIOUS_ROUND_RUN')==str(p['partial_sources']['OpenAI']['run_id']),'Wrong interrupted original run')
        prior=get('actions/runs/'+os.environ['PREVIOUS_ROUND_RUN']);origin=p['partial_sources']['OpenAI']
        require(prior['status']=='completed' and prior['conclusion']=='failure' and prior['run_attempt']==1 and
            prior['head_sha']==origin['commit'] and prior['workflow_id']==p['workflow_id'],'Interrupted original identity differs')
        completed=p['original_round3'];r2=get('actions/runs/'+str(completed['run_id']))
        require(r2['status']=='completed' and r2['conclusion']=='success' and r2['run_attempt']==1 and r2['head_sha']==completed['commit'],'Original completed round2 differs')
        fetch_named(completed['run_id'],completed['commit'],f"remaining-main-completion-{completed['run_id']}",output/'original_round3')
        proof=load(output/'original_round3/contents/round_completion.json')
        require(proof['passed'] and proof['round']==3 and proof['new_outputs']==720 and proof['records']==6480 and proof['groups']==14,'Original round2 proof incomplete')
    else:
        prior=int(os.environ['PREVIOUS_ROUND_RUN']);prev=get(f'actions/runs/{prior}')
        require(prev['status']=='completed' and prev['conclusion']=='success' and prev['run_attempt']==1 and
            prev['head_sha']==os.environ['GITHUB_SHA'] and prev['head_branch']==p['branch'] and prev['workflow_id']==p['workflow_id'],'Previous round did not finish successfully')
        fetch_named(prior,os.environ['GITHUB_SHA'],f'remaining-main-completion-{prior}',output/'previous')
        proof=load(output/'previous/contents/round_completion.json')
        require(proof['passed'] and proof['round']==r-1 and proof['new_outputs']==720 and proof['records']==6480 and proof['groups']==14,'Previous coverage round not complete')
    save(output/'entry.json',{'passed':True,'round':r,'run_id':int(os.environ['GITHUB_RUN_ID']),'commit':os.environ['GITHUB_SHA'],'model_api_calls':0})


def complete(output):
    identity();p,financial=plan();r=round_number();run=int(os.environ['GITHUB_RUN_ID']);commit=os.environ['GITHUB_SHA'];audits=[];costs={}
    for w in range(6):
        for provider in PROVIDERS:
            group=slots(provider,w)
            if not group:continue
            folder=output.parent/'downloaded_audits'/f'w{w}_{provider}'
            audit_run=run;audit_commit=commit
            if r==4 and w==0:
                reused=p['reused_wave0_audits'][provider];audit_run=reused['run_id'];audit_commit=reused['commit']
                meta=fetch_named(audit_run,audit_commit,reused['artifact_name'],folder)
                require(meta['id']==reused['artifact_id'] and sha(folder/'archive.zip')==reused['archive_sha256'] and sha(folder/'contents/independent_gate_audit.json')==reused['report_sha256'],'Reused completed wave0 evidence differs')
            else:meta=fetch_named(run,commit,artifact_name('audit',run,provider,w),folder)
            a=load(folder/'contents/independent_gate_audit.json')
            require(a['passed'] and a['evidence_complete'] and a['unresolved_reservations']==0 and
                (a['run_id'],a['commit'],a['round'],a['wave'],a['provider'])==(audit_run,audit_commit,r,w,provider) and
                a['main_programs']==len(group) and a['records']==9*len(group) and len(a['evaluation_shards'])==4,'Incomplete provider batch audit')
            require(Decimal(a['estimated_cumulative_token_cost_usd'])<=Decimal(financial['new_campaign_caps_usd'][provider]),'Existing provider cap exceeded')
            audits.append({'provider':provider,'wave':w,'artifact_id':meta['id'],'archive_sha256':sha(folder/'archive.zip'),'audit':a})
            costs[provider]=a['estimated_cumulative_token_cost_usd']
    require(len(audits)==14 and sum(x['audit']['main_programs'] for x in audits)==720 and sum(x['audit']['records'] for x in audits)==6480,'Round coverage differs')
    estimate=sum(Decimal(v) for v in costs.values())+sum(Decimal(v) for v in financial['prior_current_envelope_token_estimate_usd'].values())
    require(estimate<=45,'Cumulative cost envelope exceeded')
    save(output/'round_completion.json',{'passed':True,'round':r,'new_outputs':720,'records':6480,'groups':14,'run_id':run,'commit':commit,
        'cumulative_main_outputs':720*r,'estimated_cumulative_token_cost_usd':str(estimate),'provider_campaign_estimates_usd':costs,
        'invoice_cost_verified':False,'known_usage_token_estimate_usd':str(estimate-Decimal('0.175')),
        'approved_unknown_usage_attempts':2,'approved_operational_allowance_usd':'0.175',
        'new_model_call_coordinates':320 if r==4 else 720,'saved_partial_outputs_evaluated':160 if r==4 else 0,'reused_previously_audited_outcomes':240 if r==4 else 0,'new_measurement_outcomes':480 if r==4 else 720,
        'accounting_note':'Operational estimate includes separately approved0.025USD OpenAI and0.15USD Google allowances; actual interrupted-response usage remains unknown.', 'audits':audits,'next_round':r+1 if r<6 else None,'stop_at':4320,'model_api_calls':0,
        'completed_audit_at_utc':datetime.now(timezone.utc).isoformat(),'minimum_pass_rate':None})


def marker_name(r):return CAMPAIGN+f'-resume-advance-r{r}'


def advance_intent(output):
    identity();p,_=plan();r=round_number();require(r<6,'Stop at4320; no additional round')
    proof=load(output/'round_completion.json');require(proof['passed'] and proof['round']==r and proof['cumulative_main_outputs']==r*720,'Incomplete round')
    ref=get('git/ref/heads/'+p['branch']);require(ref['object']['sha']==os.environ['GITHUB_SHA'],'Published branch changed')
    pages=json.loads(subprocess.run(['gh','api','--paginate','--slurp',API+'actions/artifacts?per_page=100&name='+marker_name(r)],capture_output=True,check=True).stdout)
    require(pages and all(x['total_count']==0 and not x['artifacts'] for x in pages),'Advance already attempted; preserve and review')
    save(output/'advance_intent.json',{'round':r,'run_id':int(os.environ['GITHUB_RUN_ID']),'commit':os.environ['GITHUB_SHA'],
        'ref':p['branch'],'inputs':{'mode':'paid','round_id':str(r+1),'previous_run':os.environ['GITHUB_RUN_ID'],
            'verified_software_run':os.environ['VERIFIED_SOFTWARE_RUN']},'no_retry_on_uncertainty':True,'authorization_sha256':sha(PLAN)})


def advance(output):
    identity();p,_=plan();r=round_number();require(r<6,'Stop at4320')
    intent=load(output/'advance_intent.json');run=int(os.environ['GITHUB_RUN_ID']);commit=os.environ['GITHUB_SHA']
    require(intent['run_id']==run and intent['commit']==commit and intent['round']==r and intent['authorization_sha256']==sha(PLAN),'Advance intent differs')
    # Intent must already be durably uploaded before the one dispatch attempt.
    fetch_named(run,commit,marker_name(r),output.parent/'advance_guard')
    require(load(output.parent/'advance_guard/contents/advance_intent.json')==intent,'Advance guard not preserved')
    payload=json.dumps({'ref':intent['ref'],'inputs':intent['inputs']})
    subprocess.run(['gh','api','--method','POST',API+f'actions/workflows/{p["workflow_id"]}/dispatches','--input','-'],input=payload,text=True,check=True)
    save(output/'advance_accepted.json',{'accepted':True,'next_round':r+1,'at_utc':datetime.now(timezone.utc).isoformat(),'no_retry':True})


if __name__=='__main__':
    q=argparse.ArgumentParser(description=__doc__);q.add_argument('mode',choices=['software-report','entry','complete','advance-intent','advance']);q.add_argument('--output',type=Path,required=True);a=q.parse_args()
    {'software-report':software_report,'entry':entry,'complete':complete,'advance-intent':advance_intent,'advance':advance}[a.mode](a.output)
