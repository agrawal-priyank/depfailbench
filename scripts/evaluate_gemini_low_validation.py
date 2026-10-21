"""Evaluate exactly sixteen saved Gemini low validation inputs; no model calls."""
import argparse,json,shutil
from pathlib import Path
from benchmark.expanded.collect import artifact_manifest,collect,environment,implementation_manifest,save_new
from benchmark.expanded.planning import allocation,digest
from evaluate_saved_openai_validation import extract_checked
SPECS=[{'artifact_id': 12311904269, 'run_id': 39524206575, 'sha256': '684e66a2a62ace7f0ad6f99563ddf25f0d3f238bb8b967171d639cdf15987a27', 'state': 'gemini_low_feasibility'}, {'artifact_id': 12312993426, 'run_id': 39527025934, 'sha256': '333c4b62d2f4de9b1d4a45ef3607df1fce49da3beca08b3d2e3e39944b89557b', 'state': 'gemini_low_remaining'}]
def load(p):return json.loads(Path(p).read_text())
def prepare(archives,output):
    assert not output.exists(),'Preserve existing measurement evidence'
    roots=[]
    for index,(archive,spec) in enumerate(zip(archives,SPECS,strict=True)):
        assert digest(archive)==spec['sha256'],'Wrong original archive'
        dest=output/'original'/str(index);extract_checked(archive,dest)
        roots.append(dest/spec['state'])
    candidate=roots[0]/'candidate_repo/expanded_study'
    assert load(candidate/'study.json')==load(roots[1]/'candidate_repo/expanded_study/study.json')
    slots=[s for s in allocation(candidate)[1] if s['provider']=='Google']
    assert len(slots)==16 and all(s['configuration_id']=='gemini_3_8_flash_low' for s in slots)
    config=next(c for c in load(candidate/'study.json')['configurations'] if c['provider']=='Google')
    assert config['generation_settings']['thinking_level']=='low'
    original_files={str(p.relative_to(output/'original')):digest(p) for p in (output/'original').rglob('*') if p.is_file()}
    found={};manifests={}
    for root in roots:
        for d in (root/'artifacts').iterdir():
            assert d.name not in found,'Duplicate original response'
            found[d.name]=d
    assert set(found)=={s['artifact_id'] for s in slots}
    for slot in slots:
        identity=slot['artifact_id'];m=artifact_manifest(found[identity],slot,config,candidate)
        assert not m['synthetic_data']
        manifests[identity]=m
        shutil.copytree(found[identity],output/'saved_input_copies'/identity)
    save_new(output/'verified_inputs.json',{'original_archives':SPECS,'original_files':original_files,'inputs':manifests,'implementation':implementation_manifest(),'environment':environment(),'artifact_ids':[s['artifact_id'] for s in slots],'candidate_root':str(candidate),'model_api_calls':0,'main_outputs':0,'source_changes':0})
def evaluate(output):
    v=load(output/'verified_inputs.json');assert implementation_manifest()==v['implementation']
    before={str(p.relative_to(output/'original')):digest(p) for p in (output/'original').rglob('*') if p.is_file()};assert before==v['original_files']
    report=collect(output/'saved_input_copies',output/'collection',cohort='validation',artifact_ids=v['artifact_ids'],root=Path(v['candidate_root']),progress=lambda row:print(json.dumps(row),flush=True))
    assert before=={str(p.relative_to(output/'original')):digest(p) for p in (output/'original').rglob('*') if p.is_file()}
    save_new(output/'evaluation_summary.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='selected_outcomes'},indent=2),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','evaluate']);p.add_argument('--archives',type=Path,nargs=2);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.mode=='prepare':prepare(a.archives,a.output)
    else:evaluate(a.output)
