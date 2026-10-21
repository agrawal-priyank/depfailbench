"""Evaluate only saved amended-prompt validation responses; no API credentials."""
import argparse,json,os,shutil,subprocess
from pathlib import Path
from benchmark.expanded.collect import artifact_manifest,collect,implementation_manifest,save_new
from benchmark.expanded.execution_authorization import execution_snapshot
from benchmark.expanded.planning import allocation,digest
from evaluate_saved_openai_validation import extract_checked
COUNTS={'Anthropic':10,'OpenAI':40,'Google':10,'Mistral':30}
def load(p):return json.loads(Path(p).read_text())
def fetch(provider,archive,metadata):
 run=os.environ['GITHUB_RUN_ID'];commit=os.environ['GITHUB_SHA'];api='repos/agrawal-priyank/depfailbench/';name='amended-validation-'+run+'-'+provider.lower()+'-final'
 def get(path):return json.loads(subprocess.run(['gh','api',api+path],capture_output=True,check=True).stdout)
 inventory=get('actions/runs/'+run+'/artifacts?per_page=100');found=[a for a in inventory['artifacts'] if a['name']==name];assert len(found)==1 and not found[0]['expired']
 meta=get('actions/artifacts/'+str(found[0]['id']));assert meta['workflow_run']['id']==int(run) and meta['workflow_run']['head_sha']==commit
 assert not metadata.exists() and not archive.exists();archive.parent.mkdir(parents=True,exist_ok=True);save_new(metadata,meta)
 with archive.open('xb') as handle:subprocess.run(['gh','api',api+'actions/artifacts/'+str(meta['id'])+'/zip'],stdout=handle,check=True)
 assert meta['digest']=='sha256:'+digest(archive) and meta['size_in_bytes']==archive.stat().st_size
 print(json.dumps({'source_artifact_id':meta['id'],'archive_sha256':digest(archive),'model_api_calls':0}),flush=True)
def prepare(archive,metadata,output,provider):
 assert not output.exists(),'Preserve existing evidence';meta=load(metadata);run=os.environ['GITHUB_RUN_ID'];commit=os.environ['GITHUB_SHA'];expected='amended-validation-'+run+'-'+provider.lower()+'-final'
 assert meta['name']==expected and meta['workflow_run']['id']==int(run) and meta['workflow_run']['head_sha']==commit and meta['digest']=='sha256:'+digest(archive) and meta['size_in_bytes']==archive.stat().st_size
 extract_checked(archive,output/'original');state=output/'original'/provider.lower();root=state/'candidate_repo/expanded_study';m=load(state/'run_manifest.json');p=load(state/'execution_permission.json');assert not m['synthetic_data'] and m['cohort']=='validation' and m['excluded_from_main'] and m['github_run_id']==run and m['github_commit']==commit
 assert p['snapshot']==execution_snapshot(root) and p['cohort']=='validation' and p['allowed_providers']==[provider]
 slots=[s for s in allocation(root)[1] if s['provider']==provider and s['task'] in {'E4','E5','E6','E7','E8'}];assert len(slots)==COUNTS[provider] and slots==m['slots'] and {d.name for d in (state/'artifacts').iterdir()}=={s['artifact_id'] for s in slots}
 configs={c['id']:c for c in load(root/'study.json')['configurations']};inputs={}
 for s in slots:
  identity=s['artifact_id'];v=artifact_manifest(state/'artifacts'/identity,s,configs[s['configuration_id']],root);assert not v['synthetic_data'];inputs[identity]=v;shutil.copytree(state/'artifacts'/identity,output/'saved_input_copies'/identity)
 save_new(output/'verified_inputs.json',{'provider':provider,'inputs':inputs,'source_artifact_id':meta['id'],'source_archive_sha256':digest(archive),'source_run_id':int(run),'source_commit':commit,'root':str(root),'original_files':{str(p.relative_to(output/'original')):digest(p) for p in (output/'original').rglob('*') if p.is_file()},'implementation':implementation_manifest(),'model_api_calls':0,'source_repairs':0})
def evaluate(output):
 v=load(output/'verified_inputs.json');assert v['implementation']==implementation_manifest();before={str(p.relative_to(output/'original')):digest(p) for p in (output/'original').rglob('*') if p.is_file()};assert before==v['original_files']
 summary=collect(output/'saved_input_copies',output/'collection',cohort='validation',artifact_ids=list(v['inputs']),root=Path(v['root']),progress=lambda r:print(json.dumps(r),flush=True))
 assert summary['programs']==COUNTS[v['provider']] and summary['evaluation_records']==9*COUNTS[v['provider']] and not summary['confirmatory_ready'];assert before=={str(p.relative_to(output/'original')):digest(p) for p in (output/'original').rglob('*') if p.is_file()};save_new(output/'evaluation_summary.json',summary);print(json.dumps({k:v for k,v in summary.items() if k!='selected_outcomes'}),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['fetch','prepare','evaluate']);p.add_argument('--archive',type=Path);p.add_argument('--metadata',type=Path);p.add_argument('--provider',choices=list(COUNTS));p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if a.mode=='fetch':fetch(a.provider,a.archive,a.metadata)
 elif a.mode=='prepare':prepare(a.archive,a.metadata,a.output,a.provider)
 else:evaluate(a.output)
