"""Test only source-changing completed responses under the approved uniform rule.

Original archives are immutable. Derived code is explicitly labelled, contains
no repairs, and is tested without provider credentials or model calls. Selection
is based on changed bytes and original completion, never on compilation/pass.
"""
import argparse,hashlib,json,shutil
from pathlib import Path
from benchmark.expanded.collect import artifact_manifest,collect,implementation_manifest,save_new
from benchmark.expanded.execution_authorization import execution_snapshot
from benchmark.expanded.planning import allocation,assets_root,digest
from evaluate_saved_openai_validation import extract_checked
from evaluate_saved_remaining_validation import SPECS,SOURCE_RUN_ID
from source_processing_policy import process,POLICY

OLD_PROVIDER='cc0116573e387c5ea00bdecf621b6d9eed56d1467df80c3ec49204c126e709fb'
TRANSPORT_PROVIDER='1d2122128b4b0b82d6f150f680f0d7866db80a92cf6895f68bf1205f930b4711'
EXPECTED_CHANGED={'Mistral':23,'Google':3}

def derivation(metadata,text):
    result=process(text);source=result['source'];before=result.pop('original_strict_source')
    new=json.loads(json.dumps(metadata));new['original_source_sha256']=metadata['source_sha256']
    new['original_generation_status']=metadata['generation_status']
    new['source_sha256']=hashlib.sha256(source.encode()).hexdigest() if source else None
    new['source_processing']={k:v for k,v in result.items() if k!='source'}
    new['derived_for_excluded_validation']=True
    if metadata['generation_status']=='completed' and not source:new['generation_status']='no_code'
    return source,before,new

def original_inputs(output,provider):
    root=assets_root();spec=SPECS[provider];evidence=Path(output)/'original'/(spec['slug']+'_api_validation')
    plan=json.loads((evidence/'reviewed_plan.json').read_text());current=execution_snapshot(root)
    changed={k for k in current.keys()|plan['snapshot'].keys() if current.get(k)!=plan['snapshot'].get(k)}
    if changed!={'implementation/providers.py'} or plan['snapshot']['implementation/providers.py']!=OLD_PROVIDER or current['implementation/providers.py']!=TRANSPORT_PROVIDER:
        raise ValueError('only exact documented transport compatibility amendment allowed')
    slots=[s for s in allocation(root)[1] if s['provider']==provider]
    if slots!=plan['slots'] or len(slots)!=spec['count']:raise ValueError('original allocation changed')
    configs={c['id']:c for c in json.loads((root/'study.json').read_text())['configurations']}
    artifacts=evidence/'artifacts';original={};eligible=[];derived={}
    if {p.name for p in artifacts.iterdir()}!={s['artifact_id'] for s in slots}:raise ValueError('original response coordinates differ')
    for slot in slots:
        identity=slot['artifact_id'];d=artifacts/identity
        m=artifact_manifest(d,slot,configs[slot['configuration_id']],root)
        if m['synthetic_data']:raise ValueError('synthetic response cannot substitute for original')
        source,before,metadata=derivation(m['metadata'],(d/'response.txt').read_text())
        if before!=((d/'app.py').read_text() if (d/'app.py').exists() else ''):
            raise ValueError('original strict extracted source differs from saved response')
        original[identity]=m
        if source!=before and m['metadata']['generation_status']=='completed':
            eligible.append(slot);derived[identity]=(source,metadata)
    if len(eligible)!=EXPECTED_CHANGED[provider]:raise ValueError('unexpected changed-source allocation; review without cherry picking')
    return artifacts,eligible,original,derived,configs

def prepare(archive,output,provider):
    archive,output=Path(archive),Path(output)
    if digest(archive)!=SPECS[provider]['archive_sha256']:raise ValueError('wrong original archive')
    if output.exists():raise ValueError('existing derived evaluation; do not overwrite or rerun')
    extract_checked(archive,output/'original')
    artifacts,slots,original,derived,configs=original_inputs(output,provider)
    target=output/'derived/artifacts';target.mkdir(parents=True)
    manifests={}
    for slot in slots:
        identity=slot['artifact_id'];d=target/identity
        shutil.copytree(artifacts/identity,d);source,metadata=derived[identity]
        if source:(d/'app.py').write_text(source)
        elif (d/'app.py').exists():(d/'app.py').unlink()
        (d/'metadata.json').write_text(json.dumps(metadata,sort_keys=True,indent=2)+'\n')
        manifests[identity]=artifact_manifest(d,slot,configs[slot['configuration_id']],assets_root())
    report={'provider':provider,'policy':POLICY,'source_generation_run_id':SOURCE_RUN_ID,'source_artifact_id':SPECS[provider]['artifact_id'],
        'archive_sha256':SPECS[provider]['archive_sha256'],'original_response_coordinates':SPECS[provider]['count'],
        'selected_changed_completed_sources':len(slots),'selection':'all completed responses whose bytes change under the uniform single-block rule; no compilation/outcome filter',
        'derived_inputs':manifests,'original_inputs':original,'implementation':implementation_manifest(),
        'policy_module_sha256':digest(Path(__file__).with_name('source_processing_policy.py')),
        'original_files':{str(f.relative_to(output/'original')):digest(f) for f in sorted((output/'original').rglob('*')) if f.is_file()},
        'cohort':'validation','excluded_from_main':True,'model_api_calls':0,'originals_preserved':True,
        'incomplete_generation_outcomes_not_rescued':True}
    save_new(output/'verified_inputs.json',report);return report

def evaluate_saved(output,provider):
    from benchmark.expanded.report_collection import export
    output=Path(output);v=json.loads((output/'verified_inputs.json').read_text())
    _,slots,original,derived,configs=original_inputs(output,provider)
    if v['original_inputs']!=original or v['implementation']!=implementation_manifest() or v['policy']!=POLICY:
        raise ValueError('originals, core or extraction policy changed')
    if v['policy_module_sha256']!=digest(Path(__file__).with_name('source_processing_policy.py')):raise ValueError('policy code changed')
    def check():
        if v['original_files']!={str(f.relative_to(output/'original')):digest(f) for f in sorted((output/'original').rglob('*')) if f.is_file()}:
            raise ValueError('immutable original evidence changed')
        for slot in slots:
            identity=slot['artifact_id'];source,metadata=derived[identity];d=output/'derived/artifacts'/identity
            if ((d/'app.py').read_text() if (d/'app.py').exists() else '')!=source or json.loads((d/'metadata.json').read_text())!=metadata:
                raise ValueError('derived source differs from exact approved extraction')
            if artifact_manifest(d,slot,configs[slot['configuration_id']],assets_root())!=v['derived_inputs'][identity]:
                raise ValueError('derived provenance changed')
    check()
    summary=collect(output/'derived/artifacts',output/'collection',cohort='validation',artifact_ids=[s['artifact_id'] for s in slots],
                    progress=lambda row:print(json.dumps(row),flush=True))
    check();exports=export(output/'collection',output/'exports')
    return {'collection':{k:v for k,v in summary.items() if k!='selected_outcomes'},'exports':exports,
            'model_api_calls':0,'policy':POLICY,'derived_validation_only':True}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=('prepare','evaluate'))
    parser.add_argument('--provider',choices=list(SPECS),required=True);parser.add_argument('--archive',type=Path)
    parser.add_argument('--output',type=Path,required=True);a=parser.parse_args()
    if a.mode=='prepare':
        if a.archive is None:parser.error('archive required')
        r=prepare(a.archive,a.output,a.provider)
        print(json.dumps({k:v for k,v in r.items() if k not in {'derived_inputs','original_inputs','implementation','original_files'}},indent=2))
    else:
        r=evaluate_saved(a.output,a.provider);save_new(a.output/'evaluation_summary.json',r);print(json.dumps(r,indent=2))
