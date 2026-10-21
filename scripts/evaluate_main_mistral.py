"""Evaluate one predeclared Mistral task/configuration cell pair, no model calls."""
import argparse,json,os,shutil
from pathlib import Path
from benchmark.expanded.collect import artifact_manifest,collect,implementation_manifest,save_new
from benchmark.expanded.execution_authorization import execution_snapshot
from benchmark.expanded.planning import allocation,digest
from evaluate_saved_openai_validation import extract_checked

def load(p):return json.loads(Path(p).read_text())
def selected_slots(root,task,config):
    slots=[s for s in allocation(root)[0] if s['provider']=='Mistral' and s['task']==task and s['configuration_id']==config]
    if len(slots)!=60 or sum(s['condition']=='C0' for s in slots)!=30:raise ValueError('expected all sixty frozen main programs, no selection by outcome')
    return slots

def prepare(archive,metadata,output,task,config):
    meta=load(metadata);assert meta['workflow_run']['id']==int(os.environ['GITHUB_RUN_ID']) and meta['workflow_run']['head_sha']==os.environ['GITHUB_SHA']
    assert meta['name']=='main-mistral-overnight-'+os.environ['GITHUB_RUN_ID']+'-final' and meta['digest']=='sha256:'+digest(archive) and meta['size_in_bytes']==archive.stat().st_size
    assert not output.exists();extract_checked(archive,output/'original')
    state=output/'original/mistral_main_overnight';c=state/'campaign';root=c/'frozen_repo/expanded_study';p=load(c/'overnight_execution_permission.json')
    assert p['snapshot']==execution_snapshot(root) and p['allowed_providers']==['Mistral'] and p['cohort']=='main' and p['maximum_cost_usd']=='2.00'
    all_slots=[s for s in allocation(root)[0] if s['provider']=='Mistral'];assert len(all_slots)==1440 and {d.name for d in (c/'artifacts').iterdir()}=={s['artifact_id'] for s in all_slots}
    assert all((state/f'wave_{i}_summary.json').is_file() for i in range(36))
    slots=selected_slots(root,task,config);configs={c['id']:c for c in load(root/'study.json')['configurations']};inputs={}
    for slot in slots:
        identity=slot['artifact_id'];m=artifact_manifest(c/'artifacts'/identity,slot,configs[config],root);assert not m['synthetic_data'];inputs[identity]=m;shutil.copytree(c/'artifacts'/identity,output/'saved_input_copies'/identity)
    save_new(output/'verified_inputs.json',{'task':task,'configuration_id':config,'programs':60,'source_archive_sha256':digest(archive),'source_artifact_id':meta['id'],'source_run_id':meta['workflow_run']['id'],'source_commit':meta['workflow_run']['head_sha'],'inputs':inputs,'implementation':implementation_manifest(),'root':str(root),'original_files':{str(f.relative_to(output/'original')):digest(f) for f in (output/'original').rglob('*') if f.is_file()},'model_api_calls':0,'generated_code_repaired':False})

def evaluate(output):
    v=load(output/'verified_inputs.json');assert v['implementation']==implementation_manifest()
    before={str(f.relative_to(output/'original')):digest(f) for f in (output/'original').rglob('*') if f.is_file()};assert before==v['original_files']
    result=collect(output/'saved_input_copies',output/'collection',cohort='main',artifact_ids=list(v['inputs']),root=Path(v['root']),progress=lambda r:print(json.dumps(r),flush=True))
    assert result['programs']==60 and result['evaluation_records']==540 and not result['confirmatory_ready']
    assert before=={str(f.relative_to(output/'original')):digest(f) for f in (output/'original').rglob('*') if f.is_file()}
    save_new(output/'evaluation_summary.json',result);print(json.dumps({k:v for k,v in result.items() if k!='selected_outcomes'},indent=2),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','evaluate']);p.add_argument('--archive',type=Path);p.add_argument('--metadata',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--task');p.add_argument('--configuration');a=p.parse_args()
    if a.mode=='prepare':prepare(a.archive,a.metadata,a.output,a.task,a.configuration)
    else:evaluate(a.output)
