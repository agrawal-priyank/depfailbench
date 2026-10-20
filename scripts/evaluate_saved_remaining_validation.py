"""Evaluate the original excluded Mistral/Google responses without model calls.

No credential or generation imports. All original responses, missing source and
unsuccessful output statuses remain part of the fixed allocation.
"""
import argparse
import json
from pathlib import Path, PurePosixPath

from benchmark.expanded.collect import artifact_manifest, collect, implementation_manifest, save_new
from benchmark.expanded.execution_authorization import execution_snapshot
from benchmark.expanded.planning import allocation, assets_root, digest
from evaluate_saved_openai_validation import extract_checked

SPECS = {
    'Mistral': {'slug':'mistral','count':48,'artifact_id':12293643835,
                'archive_sha256':'8707a6a39cb3522ed02f5964f67ea089eeae00f208e3304207fd7a2312af4324'},
    'Google': {'slug':'google','count':16,'artifact_id':12295806138,
               'archive_sha256':'e75f10590e7ab639cb6cca0768b55562928cab7bc7c3916c07bea204b4913194'},
}
SOURCE_RUN_ID=39486369819
MEASUREMENT_AMENDMENT=None


def inputs(output,provider):
    spec=SPECS[provider];root=assets_root()
    evidence=Path(output)/'original'/(spec['slug']+'_api_validation')
    plan=json.loads((evidence/'reviewed_plan.json').read_text())
    if plan!=json.loads((root.parent/'scripts'/('expanded_'+spec['slug']+'_validation_plan.json')).read_text()):
        raise ValueError('saved provider plan differs from the exact reviewed original')
    if plan['snapshot']!=execution_snapshot(root):
        raise ValueError('original measured implementation/assets changed')
    declared=[s for s in allocation(root)[1] if s['provider']==provider]
    if declared!=plan['slots'] or len(declared)!=spec['count']:
        raise ValueError('exact original excluded provider allocation required')
    artifacts=evidence/'artifacts'
    if {p.name for p in artifacts.iterdir()}!={s['artifact_id'] for s in declared}:
        raise ValueError('missing or unexpected saved response coordinate')
    configs={c['id']:c for c in json.loads((root/'study.json').read_text())['configurations']}
    manifests={s['artifact_id']:artifact_manifest(artifacts/s['artifact_id'],s,configs[s['configuration_id']],root) for s in declared}
    if any(m['synthetic_data'] for m in manifests.values()):
        raise ValueError('synthetic responses cannot substitute for actual validation')
    return artifacts,declared,manifests


def prepare(archive,output,provider):
    spec=SPECS[provider];archive,output=Path(archive),Path(output)
    if digest(archive)!=spec['archive_sha256']:
        raise ValueError('archive differs from the verified provider evidence')
    if output.exists():raise ValueError('refusing to overwrite existing evidence')
    extract_checked(archive,output/'original')
    _,slots,manifests=inputs(output,provider)
    report={'source_generation_run_id':SOURCE_RUN_ID,'source_artifact_id':spec['artifact_id'],
        'archive_sha256':spec['archive_sha256'],'provider':provider,'cohort':'validation','excluded_from_main':True,
        'measurement_amendment':None,'programs':len(slots),'inputs':manifests,
        'implementation':implementation_manifest(),'original_files':{
            str(p.relative_to(output/'original')):digest(p) for p in sorted((output/'original').rglob('*')) if p.is_file()},
        'model_api_calls':0,'note':'Response coordinates include incomplete/no-code/format failures; no favorable replacements.'}
    save_new(output/'verified_inputs.json',report)
    return report


def original_hashes(output,verified,provider):
    original=Path(output)/'original';slug=SPECS[provider]['slug']
    present={str(p.relative_to(original)) for p in original.rglob('*') if p.is_file()}
    for extra in present-set(verified['original_files']):
        parts=PurePosixPath(extra).parts
        if (len(parts)!=5 or parts[:2]!=(slug+'_api_validation','artifacts')
                or parts[2] not in verified['inputs'] or parts[3:]!=('__pycache__','app.cpython-312.pyc')):
            raise ValueError('unexpected file added to original evidence')
    return {relative:digest(original/relative) for relative in verified['original_files']}


def evaluate_saved(output,provider):
    from benchmark.expanded.report_collection import export
    output=Path(output);verified=json.loads((output/'verified_inputs.json').read_text())
    artifacts,slots,manifests=inputs(output,provider)
    if (verified['archive_sha256']!=SPECS[provider]['archive_sha256'] or verified['inputs']!=manifests
            or verified['measurement_amendment'] is not None or verified['implementation']!=implementation_manifest()
            or verified['original_files']!=original_hashes(output,verified,provider)):
        raise ValueError('verified provider inputs changed')
    summary=collect(artifacts,output/'collection',cohort='validation',artifact_ids=[s['artifact_id'] for s in slots],
                    progress=lambda row:print(json.dumps(row),flush=True))
    if verified['original_files']!=original_hashes(output,verified,provider):
        raise ValueError('original provider evidence changed during evaluation')
    report=export(output/'collection',output/'exports')
    return {'collection':{k:v for k,v in summary.items() if k!='selected_outcomes'},'export':report,'model_api_calls':0}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('prepare','evaluate'));parser.add_argument('--provider',choices=list(SPECS),required=True)
    parser.add_argument('--archive',type=Path);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.mode=='prepare':
        if args.archive is None:parser.error('prepare requires archive')
        result=prepare(args.archive,args.output,args.provider)
        print(json.dumps({k:v for k,v in result.items() if k not in {'inputs','implementation','original_files'}},indent=2))
    else:
        result=evaluate_saved(args.output,args.provider);save_new(args.output/'evaluation_summary.json',result)
        print(json.dumps(result,indent=2))
