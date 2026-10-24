"""Verify saved research evidence and reproduce the disclosed post-review analysis.
No network, API credentials, generated-app imports or generated-program execution.
Usage: python reproduce_saved_analysis.py Supplementary_Material_S2.zip --output reproduced.json
Requires Python 3.12 and numpy==2.3.5, plus frozen trusted evaluator dependencies.
"""
from pathlib import Path
import argparse,hashlib,json,sys,tempfile,types,zipfile

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('archive',type=Path);ap.add_argument('--output',type=Path,default=Path('reproduced_analysis.json'));args=ap.parse_args()
 sha=lambda b:hashlib.sha256(b).hexdigest()
 with zipfile.ZipFile(args.archive) as z:
  root='DepFailBench_Array_Revision/'
  def read(p):return z.read(root+p)
  def load(p):return json.loads(read(p))
  inventory=load('file_inventory.json')['files']
  assert len({x['path'] for x in inventory})==len(inventory)
  for i,x in enumerate(inventory,1):
   assert sha(read(x['path']))==x['sha256'],x['path']
   if i%10000==0:print('Verified',i,'packaged file hashes',flush=True)
  join=load('data/coordinate_inventory.json');assert len(join)==4320
  review=load('analysis/repeat_difference_review.json');auth=load('analysis/post_review_analysis_authorization.json');flags={x['artifact_id'] for x in review['review']};assert len(flags)==9
  assert sha(read('analysis/repeat_difference_review.json'))==auth['review_sha256']
  manifest={x['path']:load(x['path']) for x in load('data/collection_manifests.json')}
  with tempfile.TemporaryDirectory(prefix='depfailbench_analysis_') as td:
   temp=Path(td)
   for x in inventory:
    if x['path'].startswith('code/'):
     dst=temp/x['path'];dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(read(x['path']))
   code=temp/'code';sys.path.insert(0,str(code/'src'))
   from benchmark.expanded.collect import verify_record
   from benchmark.expanded.planning import allocation
   expected={x['artifact_id']:x for x in allocation(code/'expanded_study')[0]};assert set(expected)==set(join)
   rows=[];raw=0
   for ident,x in sorted(join.items()):
    m=manifest[x['collection_manifest']];source=read(x['source_path']) if x['source_path'] else None
    assert (sha(source) if source is not None else None)==x['source_sha256']
    for deadline in [1,2,5]:
     for repeat in [1,2,3]:
      name=f'data/records/{ident}/deadline_{deadline}_repeat_{repeat}.json';record=load(name);verify_record(record,m,ident,deadline,repeat);raw+=len(record['result'].get('observations',[]))
      for field in ['task','condition','configuration_id','prompt_sha256','block_id']:
       assert record['result']['metadata'][field]==expected[ident][field]
      if deadline==1 and repeat==1:
       row=dict(record['result']);row.update(evaluation_repeat=1,synthetic_data=False,reproducibility_disagreement=ident in flags);rows.append(row)
   assert raw==346557
   source=code/'expanded_study/analysis.py';text=source.read_text();assert sha(source.read_bytes())==auth['frozen_analysis_sha256']
   original=types.ModuleType('frozen_analysis');exec(compile(text,str(source),'exec'),original.__dict__)
   try:original.summarize(rows,root=code/'expanded_study',bootstraps=1)
   except ValueError as e:assert str(e)=='repeat disagreement requires review before confirmatory analysis'
   else:raise AssertionError('Unchanged original reporting guard must reject flagged rows')
   old='''        if row.get("reproducibility_disagreement"):
            raise ValueError("repeat disagreement requires review before confirmatory analysis")'''
   new='''        if row.get("reproducibility_disagreement"):
            require_authorized_review(row)'''
   assert text.count(old)==1
   qualified=types.ModuleType('authorized_post_review_analysis')
   def require_authorized_review(row):
    assert row['metadata']['artifact_id'] in flags and row['evaluation_repeat']==1
   qualified.require_authorized_review=require_authorized_review
   exec(compile(text.replace(old,new),'<disclosed-post-review-reporting-copy>','exec'),qualified.__dict__)
   result=qualified.summarize(rows,root=code/'expanded_study',bootstraps=20000,seed=20261019)
   expected_result=load('analysis/qualified_post_review_results.json')
   for key,value in result.items():
    if key!='status':assert value==expected_result[key],key
   assert expected_result['status']=='qualified post-review analysis; not unqualified frozen confirmatory reporting'
   # Reproduce the distinct historical common-guard analysis from saved records.
   historical_source=read('historical/release_v1.1.0/source/src/benchmark/full_analysis.py')
   historical=types.ModuleType('original_historical_statistics');exec(compile(historical_source,'<original-historical-statistics>','exec'),historical.__dict__)
   archival=load('analysis/archival_reanalysis_verified.json');assert sha(historical_source)==archival['analysis_source_sha256']
   for deadline in [1,2,5]:
    oldrows=[load(f'historical/common_guard_replays/deadline_{deadline}/repeat_1/'+x['artifact_id']+'.json') for x in archival['records'] if x['deadline_s']==deadline and x['repeat']==1]
    assert len(oldrows)==320
    models={m:historical.model_analysis([r for r in oldrows if r['model']==m]) for m in ['OpenAI','Anthropic']};previous=0
    for i,m in enumerate(sorted(models,key=lambda m:models[m]['permutation_p'])):
     models[m]['holm_p']=max(previous,min(1,(2-i)*models[m]['permutation_p']));previous=models[m]['holm_p']
    assert models==archival['models'][str(deadline)]
   result.update(status='qualified post-review analysis; not unqualified frozen confirmatory reporting',records_verified=38880,historical_common_guard_statistics_reproduced=True,historical_records_in_archive=2880,raw_observations=raw,repeat_flags_preserved=sorted(flags),original_guard_verified=True,model_calls=0,generated_program_executions=0,packaged_file_hashes_verified=len(inventory))
   args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
   print(json.dumps({'outcomes':4320,'records':38880,'all_original_result_fields_reproduced':True,'model_calls':0,'generated_program_executions':0,'output':str(args.output)}))
if __name__=='__main__':main()
