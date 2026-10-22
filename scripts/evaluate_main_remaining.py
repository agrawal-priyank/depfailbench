"""Four independent Linux shards per batch; saved-record and raw-stream audit."""
import argparse, ast, json, os, shutil, sqlite3, hashlib
from collections import Counter
from decimal import Decimal
from pathlib import Path
from benchmark.expanded.collect import artifact_manifest, collect, implementation_manifest, audit_collection, verify_record
from benchmark.expanded.execution_authorization import execution_snapshot
from benchmark.expanded.contracts import Settings
from benchmark.expanded.oracles import classify
from benchmark.expanded.providers import build_request, TokenRates
from benchmark.expanded.provider_recovery import replay_wire
from continue_main_remaining import PLAN, CAMPAIGN, PROVIDERS, plan, slots, generation_slots, prefix, round_number, identity, artifact_name, fetch_named, files, ledger_rows, load, sha, require
from record_evaluation_host import write_record


def save(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f:f.write(json.dumps(value,indent=2)+'\n')


def selected(provider,wave,shard,root=None):
    require(type(shard) is int and 0<=shard<4,'Invalid partition')
    return slots(provider,wave,root)[shard::4]


def verify_archive(folder,run,commit,name):
    m=load(folder/'metadata.json')
    require(m['name']==name and m['workflow_run']['id']==run and m['workflow_run']['head_sha']==commit and
            m['digest']=='sha256:'+sha(folder/'archive.zip') and m['size_in_bytes']==(folder/'archive.zip').stat().st_size,'Archive identity/digest mismatch')
    return m


def verify_generation(source,provider,wave,run,commit):
    p,financial=plan();r=round_number()
    meta=verify_archive(source,run,commit,artifact_name('generation',run,provider,wave))
    outer=source/'contents'/provider.lower();state=outer/'campaign';root=state/'frozen_repo/expanded_study'
    m=load(outer/'wave_manifest.json');summary=load(outer/'generation_summary.json');permission=load(state/m['permission_path'])
    require(sha(root/'study.json')==p['frozen_study_sha256'] and load(state/'reviewed_plan.json')==financial,'Study/financial plan differs')
    require(m['slots']==slots(provider,wave,root) and m['run_id']==run and m['commit']==commit and
            m['provider']==provider and m['wave']==wave and m['round']==r and m['plan_sha256']==sha(PLAN),'Batch identity differs')
    require(not m['synthetic_data'] and m['campaign_namespace']==CAMPAIGN and m['source_repairs']==0,'Source integrity differs')
    require(permission['snapshot']==execution_snapshot(root) and permission['cohort']=='main' and permission['allowed_providers']==[provider] and
            permission['allowed_artifact_ids']==[s['artifact_id'] for s in generation_slots(provider,wave,root)] and
            permission['maximum_cost_usd']==financial['new_campaign_caps_usd'][provider],'Permission identity differs')
    require(summary['complete'] and summary['programs']==len(slots(provider,wave,root)) and summary['cumulative_programs']==len(prefix(provider,wave,root)) and
            not summary['ledger']['held'] and not summary['ledger']['pauses'],'Incomplete generation or unresolved usage')
    require({f.name for f in (state/'artifacts').iterdir()}=={s['artifact_id'] for s in prefix(provider,wave,root)},'Wrong cumulative source prefix')
    return meta,outer,state,root,m


def prepare(provider,wave,shard,output):
    identity();require(not output.exists(),'Never overwrite evaluation')
    run=int(os.environ['GITHUB_RUN_ID']);commit=os.environ['GITHUB_SHA']
    source=Path('saved')/provider/f'r{round_number()}w{wave}s{shard}'
    fetch_named(run,commit,artifact_name('generation',run,provider,wave),source)
    meta,outer,state,root,m=verify_generation(source,provider,wave,run,commit)
    configs={c['id']:c for c in load(root/'study.json')['configurations']};inputs={}
    for slot in selected(provider,wave,shard,root):
        ident=slot['artifact_id'];inputs[ident]=artifact_manifest(state/'artifacts'/ident,slot,configs[slot['configuration_id']],root)
        require(not inputs[ident]['synthetic_data'],'Synthetic main input')
        shutil.copytree(state/'artifacts'/ident,output/'saved_input_copies'/ident)
    save(output/'verified_inputs.json',{'provider':provider,'round':round_number(),'wave':wave,'shard':shard,
        'campaign_namespace':CAMPAIGN,'inputs':inputs,'generation_artifact':meta,'source_run_id':run,'source_commit':commit,
        'root':str(root),'implementation':implementation_manifest(),'plan_sha256':sha(PLAN),'model_api_calls':0,'source_repairs':0})


def evaluate(provider,wave,shard,output):
    # No credential used in fetching may reach a generated program.
    require(not any(k in os.environ for k in ['GH_TOKEN','GITHUB_TOKEN','REMAINING_PROVIDER_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY','GOOGLE_API_KEY','GEMINI_API_KEY','MISTRAL_API_KEY']),'Credentials present in evaluation')
    identity();v=load(output/'verified_inputs.json')
    require((v['provider'],v['round'],v['wave'],v['shard'])==(provider,round_number(),wave,shard) and
            v['source_run_id']==int(os.environ['GITHUB_RUN_ID']) and v['source_commit']==os.environ['GITHUB_SHA'] and
            v['plan_sha256']==sha(PLAN) and v['implementation']==implementation_manifest() and not(output/'collection').exists(),'Evaluation identity differs or already exists')
    before=files(output/'saved_input_copies');write_record(output/'host_metadata.json');host_hash=sha(output/'host_metadata.json')
    summary=collect(output/'saved_input_copies',output/'collection',cohort='main',artifact_ids=list(v['inputs']),root=Path(v['root']),
                    progress=lambda r:print(json.dumps(r),flush=True))
    require(summary['complete_matrix'] and summary['programs']==len(v['inputs']) and summary['evaluation_records']==9*len(v['inputs']) and
            not summary['confirmatory_ready'] and before==files(output/'saved_input_copies') and host_hash==sha(output/'host_metadata.json'),'Incomplete or changed evaluation')
    save(output/'evaluation_integrity.json',{'host_metadata_sha256':host_hash,'source_repairs':0})
    save(output/'evaluation_summary.json',summary)


def verify_single_unknown_usage(art,attempt,provider,slot,j,headers,complete,metadata):
    """Narrow hash-bound exemption; a second unknown response still fails closed."""
    e=load(PLAN)['approved_usage_exception']
    if slot['artifact_id']!=e['artifact_id']:return False
    require(provider=='OpenAI' and slot['round']==3 and len(list(art.glob('attempt_*')))==1 and
        complete['wire_sha256']==sha(attempt/'wire_response.bin')==e['wire_sha256'] and headers['http_status']==200 and headers['x-request-id']==e['request_id'] and j['id']==e['attempt_id'] and j['number']==1 and
        j['consumed'] and j['billing_uncertain'] and j['estimated_token_cost_usd'] is None and
        not j['usage']['complete'] and metadata['estimated_token_cost_usd'] is None and
        metadata['provider_response_id']==e['response_id'] and metadata['generation_status']=='incomplete' and
        metadata['source_sha256'] is None and not(art/'app.py').exists(),'Approved interrupted coordinate differs')
    replay=replay_wire(provider,(attempt/'wire_response.bin').read_bytes(),headers,complete);parsed=replay['parsed']
    require(not replay['terminal_received'] and replay['consumed'] and replay['raw']==load(attempt/'assembled_response.json') and
        parsed['usage']==j['usage']==metadata['provider_usage'] and parsed['usage']['raw'] is None and
        parsed['generation_status']==metadata['generation_status'] and parsed['source_processing']==metadata['source_processing'] and
        not parsed['source'] and parsed['text']==(art/'response.txt').read_text(),'Approved raw unknown-usage outcome differs')
    return True


def audit_finance(outer,state,root,provider,wave):
    """Replay every cumulative request, wire response, usage and settled charge."""
    financial=load(state/'reviewed_plan.json');current=load(outer/'wave_manifest.json');permission=load(state/current['permission_path'])
    configs={c['id']:c for c in load(root/'study.json')['configurations']};cost=Decimal(0);attempt_count=0;parse_counts=Counter();inputs={}
    for slot in prefix(provider,wave,root):
        ident=slot['artifact_id'];art=state/'artifacts'/ident;config=configs[slot['configuration_id']]
        original=artifact_manifest(art,slot,config,root);metadata=original['metadata'];consumed=0
        require(not original['synthetic_data'],'Synthetic original')
        expected_request=build_request(config,(art/'prompt.txt').read_text())
        for attempt in sorted(art.glob('attempt_*')):
            attempt_count+=1;j=load(attempt/'attempt.json');headers=load(attempt/'response_headers.json');complete=load(attempt/'wire_complete.json')
            require(load(attempt/'request.json')==expected_request and complete['wire_sha256']==sha(attempt/'wire_response.bin') and
                    not j['simulation_only'],'Request/wire integrity issue')
            exception=verify_single_unknown_usage(art,attempt,provider,slot,j,headers,complete,metadata)
            if exception:
                consumed+=1;cost+=Decimal('0.025');continue
            require(not j['billing_uncertain'],'Unapproved usage uncertainty')
            cost+=Decimal(j['estimated_token_cost_usd'])
            if headers['http_status']!=200:
                require(j['retryable'] and not j['consumed'] and Decimal(j['estimated_token_cost_usd'])==0,'Unexpected unsuccessful attempt');continue
            replay=replay_wire(provider,(attempt/'wire_response.bin').read_bytes(),headers,complete)
            require(replay['terminal_received'] and not replay['error_kind'] and replay['raw']==load(attempt/'assembled_response.json'),'Incomplete raw stream')
            parsed=replay['parsed'];require(parsed['usage']['complete'] and parsed['usage']==j['usage'] and
                TokenRates(**financial['token_rates'][slot['model_id']]).estimate(parsed['usage'])==j['estimated_token_cost_usd'],'Usage/cost replay differs')
            if j['consumed']:
                consumed+=1;require(parsed['generation_status']==metadata['generation_status'] and parsed['usage']==metadata['provider_usage'] and
                    parsed['text']==(art/'response.txt').read_text() and parsed['source_processing']==metadata['source_processing'],'Provider source replay differs')
                require(parsed['source']==(art/'app.py').read_text() if parsed['source'] else not(art/'app.py').exists(),'Source bytes differ')
        require(consumed==1,'Exactly one consumed generation required')
        if slot not in slots(provider,wave,root):continue
        inputs[ident]=original
        if not(art/'app.py').exists():parse_counts['no_source']+=1
        else:
            try:ast.parse((art/'app.py').read_text());parse_counts['parses']+=1
            except SyntaxError:parse_counts['syntax_error']+=1
    rows=ledger_rows(state/'spending.sqlite');settings={r['name']:r['value'] for r in rows['settings']};attempts=rows['attempts']
    require(len(attempts)==attempt_count and all(a['state']=='settled' and a['charged'] is not None for a in attempts) and not rows['pauses'],'Unsettled ledger')
    require(sum(a['charged'] for a in attempts)==int(cost*Decimal(10**9)) and cost<=Decimal(permission['maximum_cost_usd']) and
        settings['limit']==str(int(Decimal(permission['maximum_cost_usd'])*10**9)) and settings['execution_permit']==sha(state/current['permission_path']) and
        Decimal(load(outer/'generation_summary.json')['estimated_cumulative_token_cost_usd'])==cost,'Ledger cost/cap/permission differs')
    exception_rows=[a for a in attempts if a['id']==load(PLAN)['approved_usage_exception']['attempt_id']]
    if exception_rows:
        require(len(exception_rows)==1 and exception_rows[0]['charged']==25000000,'Approved allowance differs')
        evidence=[a for a in rows['audit'] if a['event']=='reconcile_cost' and json.loads(a['details'])['attempt_id']==exception_rows[0]['id']]
        require(len(evidence)==1 and json.loads(evidence[0]['details'])['evidence']['sha256']==load(PLAN)['approved_recovery_authorization_sha256'],'Author exception audit evidence differs')
    if round_number()==3 and wave==0:
        spec=load(PLAN)['partial_sources'][provider]
        require(load(outer/'original_interrupted_ledger_rows.json')==ledger_rows(outer/'original_interrupted_ledger.sqlite') and sha(outer/'original_interrupted_ledger.sqlite')==spec['original_ledger_sha256'],'Original interrupted ledger not preserved')
        require(hashlib.sha256(json.dumps(load(outer/'prior_campaign_files.json'),sort_keys=True).encode()).hexdigest()==spec['campaign_files_sha256'],'Retained source manifest differs')
    prior=load(outer/'prior_ledger_rows.json')
    require(all(a in attempts for a in prior['attempts']) and all(s in rows['slots'] for s in prior['slots']) and
        rows['audit'][:len(prior['audit'])]==prior['audit'] and all(sha(state/name)==h for name,h in load(outer/'prior_campaign_files.json').items() if name!='spending.sqlite'),'Prior bytes or charges changed')
    return inputs,dict(parse_counts),cost,cost-Decimal(sum(a['charged'] for a in prior['attempts']))/Decimal(10**9),attempt_count


def audit_saved(source,shards,provider,wave,run,commit):
    meta,outer,state,root,m=verify_generation(source,provider,wave,run,commit)
    before=files(state);inputs,parses,cost,new_cost,attempts=audit_finance(outer,state,root,provider,wave)
    rows=[];probes=0;flags=[];literal=[];variations=[];proofs=[]
    require(set(shards)==set(range(4)),'Missing shard')
    for shard,folder in sorted(shards.items()):
        em=verify_archive(folder,run,commit,artifact_name('evaluation',run,provider,wave,shard=shard));base=folder/'contents'
        v=load(base/'verified_inputs.json');manifest=load(base/'collection/collection_manifest.json')
        wanted={s['artifact_id'] for s in selected(provider,wave,shard,root)}
        require((v['provider'],v['round'],v['wave'],v['shard'])==(provider,round_number(),wave,shard) and
            v['source_run_id']==run and v['source_commit']==commit and v['plan_sha256']==sha(PLAN) and v['generation_artifact']==meta,'Shard linkage differs')
        require(manifest['inputs']==v['inputs']=={k:inputs[k] for k in wanted} and
            v['implementation']==manifest['implementation']==implementation_manifest() and manifest['cohort']=='main' and
            not manifest['synthetic_data'] and manifest['selected_repeat']==1,'Shard inputs/implementation differ')
        require(manifest['environment']['platform'].startswith('Linux-') and manifest['environment']['python'].startswith('3.12.14') and
            manifest['environment']['machine']=='x86_64','Wrong measurement platform')
        for ident,data in v['inputs'].items():
            require(all(sha(base/'saved_input_copies'/ident/name)==h for name,h in data['files'].items()),'Source copy changed')
        before_summary=(base/'collection/collection_summary.json').read_bytes();summary=audit_collection(base/'collection')
        require(before_summary==(base/'collection/collection_summary.json').read_bytes() and summary==load(base/'evaluation_summary.json') and
            summary['complete_matrix'] and summary['evaluation_records']==9*len(wanted) and not summary['confirmatory_ready'],'Incomplete shard')
        host=load(base/'host_metadata.json')
        require(load(base/'evaluation_integrity.json')['host_metadata_sha256']==sha(base/'host_metadata.json') and
            host['workflow_and_image']['GITHUB_RUN_ID']==str(run) and host['workflow_and_image']['GITHUB_SHA']==commit and
            host['platform'].startswith('Linux-') and host['machine']=='x86_64' and host['logical_cpus_os_count']>0,'Host provenance differs')
        part=[load(f) for f in (base/'collection/records').glob('*/*.json')]
        expected={(i,d,r) for i in wanted for d in [1,2,5] for r in [1,2,3]}
        require(len(part)==len(expected) and {(r['artifact_id'],r['deadline_s'],r['evaluation_repeat']) for r in part}==expected,'Records missing/duplicated')
        for row in part:
            verify_record(row,manifest,row['artifact_id'],row['deadline_s'],row['evaluation_repeat'])
            for o in row['result']['observations']:
                independent=classify(row['result']['task'],o['scenario'],Settings(deadline_s=row['deadline_s']),o)
                require(all(o[k]==val for k,val in independent.items()),'Raw observation reclassification differs');probes+=1
        rows.extend(part);flags+=summary['reproducibility_disagreements'];literal+=summary['literal_trace_disagreements'];variations+=summary['permitted_internal_identifier_variations']
        proofs.append({'shard':shard,'artifact_id':em['id'],'archive_sha256':sha(folder/'archive.zip'),'host_metadata_sha256':sha(base/'host_metadata.json')})
    n=len(slots(provider,wave,root));require(len(rows)==9*n and before==files(state),'Cumulative evidence changed')
    counts={}
    for d in [1,2,5]:
        chosen=[r['result'] for r in rows if r['deadline_s']==d and r['evaluation_repeat']==1]
        counts[str(d)]={'programs':n,'functional_qualified':sum(r['clean_qualified'] for r in chosen),'all_checks_passed':sum(r['primary_pass'] for r in chosen)}
    return {'passed':True,'provider':provider,'run_id':run,'commit':commit,'round':round_number(),'wave':wave,'campaign_namespace':CAMPAIGN,
        'main_programs':n,'records':9*n,'cumulative_provider_programs':len(prefix(provider,wave,root)),'raw_probes_reclassified':probes,
        'counts_by_deadline':counts,'source_parse_counts':parses,'estimated_cumulative_token_cost_usd':str(cost),'estimated_token_cost_usd':str(new_cost),
        'generation_archive_sha256':sha(source/'archive.zip'),'generation_artifact_id':meta['id'],'evaluation_shards':proofs,'invoice_cost_verified':False,
        'http_attempts':attempts,'unresolved_reservations':0,
        'approved_unknown_usage_responses':1 if provider=='OpenAI' else 0,'approved_operational_allowance_usd':'0.025' if provider=='OpenAI' else '0',
        'known_usage_token_estimate_usd':str(cost-(Decimal('0.025') if provider=='OpenAI' else Decimal(0))),
        'accounting_note':'Compatibility cost fields are operational estimates including the single approved allowance; actual usage for that response remains unknown, never invoice verified.',
        'new_model_call_coordinates':len(generation_slots(provider,wave,root)),'behavioral_repeat_disagreements':flags,'literal_trace_disagreements':literal,
        'permitted_internal_identifier_variations':variations,'evidence_complete':True,'model_api_calls':0,'generated_program_executions_by_audit':0,
        'gate_note':'Integrity and original spending limits only; generated-program failures remain outcomes. No pass-rate threshold, repairs or replacements.'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['prepare','evaluate','audit'])
    p.add_argument('--provider',choices=PROVIDERS,required=True);p.add_argument('--wave',type=int,required=True);p.add_argument('--shard',type=int);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.mode=='prepare':prepare(a.provider,a.wave,a.shard,a.output)
    elif a.mode=='evaluate':evaluate(a.provider,a.wave,a.shard,a.output)
    else:
        identity();run=int(os.environ['GITHUB_RUN_ID']);commit=os.environ['GITHUB_SHA'];base=Path('saved_audit')/a.provider/f'r{round_number()}w{a.wave}'
        source=base/'generation';fetch_named(run,commit,artifact_name('generation',run,a.provider,a.wave),source);parts={}
        for s in range(4):
            parts[s]=base/f'evaluation_s{s}';fetch_named(run,commit,artifact_name('evaluation',run,a.provider,a.wave,shard=s),parts[s])
        report=audit_saved(source,parts,a.provider,a.wave,run,commit);save(a.output/'independent_gate_audit.json',report);print(json.dumps(report),flush=True)
