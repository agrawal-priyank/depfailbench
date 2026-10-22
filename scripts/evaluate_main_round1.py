"""Credential-free saved-code evaluation and read-only round-one continuation audit."""
import argparse,json,os,shutil,subprocess
import ast,sqlite3
from decimal import Decimal
from pathlib import Path
from collections import Counter
from benchmark.expanded.collect import artifact_manifest,collect,implementation_manifest,audit_collection,verify_record
from benchmark.expanded.execution_authorization import execution_snapshot
from benchmark.expanded.planning import allocation,digest
from benchmark.expanded.contracts import Settings
from benchmark.expanded.oracles import classify
from evaluate_saved_openai_validation import extract_checked
from staged_main_first_gate import CAMPAIGN,PROVIDERS
from continue_main_round1 import slots as wave_slots,prefix,artifact_name,fetch_named,files,ledger_rows,plan as continuation_plan
from benchmark.expanded.providers import build_request,TokenRates
from benchmark.expanded.provider_recovery import replay_wire


def load(p):return json.loads(Path(p).read_text())
def save(p,d):
    Path(p).parent.mkdir(parents=True,exist_ok=True)
    with Path(p).open('x') as f:f.write(json.dumps(d,indent=2)+'\n')


def fetch(provider,wave,output,kind='generation'):
    fetch_named(int(os.environ['GITHUB_RUN_ID']),os.environ['GITHUB_SHA'],
                artifact_name(kind,int(os.environ['GITHUB_RUN_ID']),provider,wave),output)


def prepare(source,output,provider,wave):
    assert not output.exists(),'Preserve existing evaluation evidence'
    continuation_plan();meta=load(source/'metadata.json');run=int(os.environ['GITHUB_RUN_ID']);commit=os.environ['GITHUB_SHA']
    assert meta['name']==artifact_name('generation',run,provider,wave)
    assert meta['workflow_run']['id']==run and meta['workflow_run']['head_sha']==commit
    assert meta['digest']=='sha256:'+digest(source/'archive.zip') and meta['size_in_bytes']==(source/'archive.zip').stat().st_size
    extract_checked(source/'archive.zip',output/'original')
    outer=output/'original'/provider.lower();state=outer/'campaign';root=state/'frozen_repo/expanded_study'
    m=load(outer/'wave_manifest.json');summary=load(outer/'generation_summary.json');p=load(state/m['permission_path'])
    slots=wave_slots(provider,wave,root)
    assert m['slots']==slots and m['run_id']==run and m['commit']==commit and m['provider']==provider and m['wave']==wave
    assert not m['synthetic_data'] and m['campaign_namespace']==CAMPAIGN and m['source_repairs']==0
    assert p['snapshot']==execution_snapshot(root) and p['cohort']=='main' and p['allowed_providers']==[provider]
    assert p['allowed_artifact_ids']==[s['artifact_id'] for s in slots]
    assert summary['complete'] and summary['programs']==len(slots) and summary['cumulative_programs']==len(prefix(provider,wave,root))
    assert not summary['ledger']['held'] and not summary['ledger']['pauses']
    assert {f.name for f in (state/'artifacts').iterdir()}=={s['artifact_id'] for s in prefix(provider,wave,root)}
    configs={c['id']:c for c in load(root/'study.json')['configurations']};inputs={}
    for slot in slots:
        identity=slot['artifact_id'];v=artifact_manifest(state/'artifacts'/identity,slot,configs[slot['configuration_id']],root)
        assert not v['synthetic_data'];inputs[identity]=v
        shutil.copytree(state/'artifacts'/identity,output/'saved_input_copies'/identity)
    save(output/'verified_inputs.json',{'provider':provider,'wave':wave,'campaign_namespace':CAMPAIGN,'inputs':inputs,
        'source_artifact_id':meta['id'],'source_archive_sha256':digest(source/'archive.zip'),'source_run_id':run,
        'source_commit':commit,'root':str(root),'implementation':implementation_manifest(),
        'original_files':files(output/'original'),'model_api_calls':0,'source_repairs':0})


def evaluate(output):
    v=load(output/'verified_inputs.json');assert v['implementation']==implementation_manifest()
    before={str(f.relative_to(output/'original')):digest(f) for f in (output/'original').rglob('*') if f.is_file()}
    assert before==v['original_files']
    host_hash=digest(output/'host_metadata.json')
    summary=collect(output/'saved_input_copies',output/'collection',cohort='main',artifact_ids=list(v['inputs']),
        root=Path(v['root']),progress=lambda r:print(json.dumps(r),flush=True))
    assert summary['programs']==len(v['inputs']) and summary['evaluation_records']==9*len(v['inputs']) and not summary['confirmatory_ready']
    assert before=={str(f.relative_to(output/'original')):digest(f) for f in (output/'original').rglob('*') if f.is_file()}
    assert host_hash==digest(output/'host_metadata.json')
    save(output/'evaluation_integrity.json',{'host_metadata_sha256':host_hash,'source_repairs':0})
    save(output/'evaluation_summary.json',summary)


def audit_saved(base,provider,wave,run,commit):
    continuation_plan()
    v=load(base/'verified_inputs.json');manifest=load(base/'collection/collection_manifest.json')
    assert v['provider']==provider and v['campaign_namespace']==CAMPAIGN and v['source_run_id']==run and v['source_commit']==commit
    assert manifest['inputs']==v['inputs'] and manifest['cohort']=='main' and not manifest['synthetic_data']
    assert v['implementation']==manifest['implementation']==implementation_manifest()
    assert manifest['environment']['platform'].startswith('Linux-') and manifest['environment']['python'].startswith('3.12.14')
    assert manifest['environment']['machine']=='x86_64' and manifest['selected_repeat']==1
    outer=base/'original'/provider.lower();state=outer/'campaign';root=state/'frozen_repo/expanded_study'
    current=load(outer/'wave_manifest.json');assert current['wave']==wave and current['run_id']==run and current['commit']==commit and current['slots']==wave_slots(provider,wave,root)
    slots=wave_slots(provider,wave,root);n=len(slots);assert v['wave']==wave and len(v['inputs'])==n and set(v['inputs'])=={s['artifact_id'] for s in slots}
    configs={c['id']:c for c in load(root/'study.json')['configurations']}
    plan=load(state/'reviewed_plan.json');permission=load(state/current['permission_path'])
    assert permission['snapshot']==execution_snapshot(root) and permission['allowed_providers']==[provider]
    assert permission['allowed_artifact_ids']==[s['artifact_id'] for s in slots]
    assert permission['maximum_cost_usd']==plan['new_campaign_caps_usd'][provider]
    cost=Decimal(0);attempt_count=0;parse_counts=Counter()
    for slot in prefix(provider,wave,root):
        identity=slot['artifact_id'];art=state/'artifacts'/identity
        original=artifact_manifest(art,slot,configs[slot['configuration_id']],root)
        if slot in slots:
            assert original==v['inputs'][identity]
            assert all(digest(base/'saved_input_copies'/identity/name)==h for name,h in v['inputs'][identity]['files'].items())
        metadata=original['metadata'];config=configs[slot['configuration_id']]
        expected_request=build_request(config,(art/'prompt.txt').read_text());consumed=0
        for attempt in sorted(art.glob('attempt_*')):
            attempt_count+=1;j=load(attempt/'attempt.json');headers=load(attempt/'response_headers.json');complete=load(attempt/'wire_complete.json')
            assert load(attempt/'request.json')==expected_request and complete['wire_sha256']==digest(attempt/'wire_response.bin')
            assert not j['billing_uncertain'] and not j['simulation_only'];cost+=Decimal(j['estimated_token_cost_usd'])
            if headers['http_status']!=200:
                assert j['retryable'] and not j['consumed'] and Decimal(j['estimated_token_cost_usd'])==0
                continue
            replay=replay_wire(provider,(attempt/'wire_response.bin').read_bytes(),headers,complete)
            assert replay['terminal_received'] and not replay['error_kind'] and replay['raw']==load(attempt/'assembled_response.json')
            parsed=replay['parsed'];assert parsed['usage']['complete'] and parsed['usage']==j['usage']
            assert TokenRates(**plan['token_rates'][slot['model_id']]).estimate(parsed['usage'])==j['estimated_token_cost_usd']
            if j['consumed']:
                consumed+=1;assert parsed['generation_status']==metadata['generation_status'] and parsed['usage']==metadata['provider_usage']
                assert parsed['text']==(art/'response.txt').read_text() and parsed['source_processing']==metadata['source_processing']
                if parsed['source']:assert parsed['source']==(art/'app.py').read_text()
                else:assert not(art/'app.py').exists()
        assert consumed==1
        if slot not in slots:continue
        if not(art/'app.py').exists():parse_counts['no_source']+=1
        else:
            try:ast.parse((art/'app.py').read_text());parse_counts['parses']+=1
            except SyntaxError:parse_counts['syntax_error']+=1
    db=sqlite3.connect('file:'+str((state/'spending.sqlite').resolve())+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    attempts=[dict(r) for r in db.execute('select * from attempts')];pauses=list(db.execute('select * from pauses'));settings=dict(db.execute('select name,value from settings'));db.close()
    assert len(attempts)==attempt_count and all(a['state']=='settled' and a['charged'] is not None for a in attempts) and not pauses
    assert sum(a['charged'] for a in attempts)==int(cost*Decimal(10**9))
    assert settings['limit']==str(int(Decimal(permission['maximum_cost_usd'])*10**9)) and settings['execution_permit']==digest(state/current['permission_path'])
    assert Decimal(load(outer/'generation_summary.json')['estimated_cumulative_token_cost_usd'])==cost
    assert v['original_files']=={str(f.relative_to(base/'original')):digest(f) for f in (base/'original').rglob('*') if f.is_file()}
    prior_rows=load(outer/'prior_ledger_rows.json')
    assert all(a in attempts for a in prior_rows['attempts'])
    assert all(digest(state/name)==h for name,h in load(outer/'prior_campaign_files.json').items() if name!='spending.sqlite')
    rows=[load(f) for f in (base/'collection/records').glob('*/*.json')];assert len(rows)==9*n
    expected={(s['artifact_id'],d,r) for s in slots for d in [1,2,5] for r in [1,2,3]}
    assert {(r['artifact_id'],r['deadline_s'],r['evaluation_repeat']) for r in rows}==expected
    probes=0
    for row in rows:
        verify_record(row,manifest,row['artifact_id'],row['deadline_s'],row['evaluation_repeat'])
        for o in row['result']['observations']:
            independent=classify(row['result']['task'],o['scenario'],Settings(deadline_s=row['deadline_s']),o)
            assert all(o[k]==value for k,value in independent.items());probes+=1
    before=(base/'collection/collection_summary.json').read_bytes()
    summary=audit_collection(base/'collection')
    assert before==(base/'collection/collection_summary.json').read_bytes() and summary==load(base/'evaluation_summary.json')
    assert summary['complete_matrix'] and not summary['confirmatory_ready']
    host=load(base/'host_metadata.json')
    assert load(base/'evaluation_integrity.json')['host_metadata_sha256']==digest(base/'host_metadata.json')
    assert host['workflow_and_image']['GITHUB_RUN_ID']==str(run) and host['workflow_and_image']['GITHUB_SHA']==commit
    assert host['platform'].startswith('Linux-') and host['machine']=='x86_64' and host['logical_cpus_os_count']>0
    counts={}
    for d in [1,2,5]:
        selected=[r['result'] for r in rows if r['deadline_s']==d and r['evaluation_repeat']==1]
        counts[str(d)]={'programs':n,'functional_qualified':sum(r['clean_qualified'] for r in selected),'all_checks_passed':sum(r['primary_pass'] for r in selected)}
    return {'passed':True,'provider':provider,'run_id':run,'commit':commit,'campaign_namespace':CAMPAIGN,
        'main_programs':n,'records':9*n,'wave':wave,'cumulative_provider_programs':len(prefix(provider,wave,root)),'raw_probes_reclassified':probes,'counts_by_deadline':counts,
        'source_parse_counts':dict(parse_counts),'estimated_cumulative_token_cost_usd':str(cost),'estimated_token_cost_usd':str(cost-Decimal(sum(a['charged'] for a in prior_rows['attempts']))/Decimal(10**9)),'generation_archive_sha256':v['source_archive_sha256'],'invoice_cost_verified':False,
        'http_attempts':attempt_count,'unresolved_reservations':0,
        'behavioral_repeat_disagreements':summary['reproducibility_disagreements'],
        'literal_trace_disagreements':summary['literal_trace_disagreements'],
        'permitted_internal_identifier_variations':summary['permitted_internal_identifier_variations'],
        'evidence_complete':True,'continuation_released':False,
        'gate_note':'Evidence integrity only. Generated-program failures are retained outcomes; no minimum model pass rate.',
        'model_api_calls':0,'generated_program_executions_by_audit':0}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['fetch','prepare','evaluate','audit'])
    p.add_argument('--provider',choices=PROVIDERS,required=True);p.add_argument('--wave',type=int,required=True)
    p.add_argument('--source',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--kind',choices=['generation','evaluation'],default='generation');a=p.parse_args()
    if a.mode=='fetch':fetch(a.provider,a.wave,a.output,a.kind)
    elif a.mode=='prepare':prepare(a.source,a.output,a.provider,a.wave)
    elif a.mode=='evaluate':evaluate(a.output)
    else:
        report=audit_saved(a.output,a.provider,a.wave,int(os.environ['GITHUB_RUN_ID']),os.environ['GITHUB_SHA'])
        save(a.output/'independent_gate_audit.json',report);print(json.dumps(report,indent=2))
