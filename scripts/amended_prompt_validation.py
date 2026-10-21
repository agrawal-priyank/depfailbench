"""Exactly ninety excluded checks of five amended task prompts; no main calls."""
import argparse,asyncio,hashlib,json,os,shutil,subprocess
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
import httpx
from benchmark.expanded.collect import artifact_manifest
from benchmark.expanded.execution_authorization import ExecutionPermit,execution_snapshot
from benchmark.expanded.live_generation import LiveGenerator
from benchmark.expanded.planning import allocation,assets_root,check
from benchmark.expanded.provider_generation import save_json
from benchmark.expanded.provider_dry_run import fixture,sse_bytes,stream_events
from benchmark.expanded.providers import TokenRates
from benchmark.expanded.spending import DispatchPaused,SpendingLedger
ROOT=Path(__file__).resolve().parents[1];PLAN=ROOT/'scripts/amended_prompt_validation_plan.json';BATCH='amended-prompts-20261021-v1';TASKS={'E4','E5','E6','E7','E8'}
COUNTS={'Anthropic':10,'OpenAI':40,'Google':10,'Mistral':30};CAPS={'Anthropic':'1.25','OpenAI':'1.25','Google':'0.45','Mistral':'0.05'}
def load(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(ok,msg):
 if not ok:raise DispatchPaused(msg)
def slots(provider,root=None):return [s for s in allocation(root)[1] if s['provider']==provider and s['task'] in TASKS]
def plan():
 p=load(PLAN);require(p['batch_id']==BATCH and p['author_authorized'] is True,'reviewed check authorization missing');require(p['snapshot']==execution_snapshot() and p['driver_sha256']==sha(Path(__file__)),'reviewed prompts/core/driver changed')
 require(p['providers']==CAPS and sum(Decimal(x) for x in p['providers'].values())==3,'reviewed spending scope differs')
 require(p['evaluation_driver_sha256']==sha(ROOT/'scripts/evaluate_amended_validation.py'),'evaluation driver changed')
 for provider,n in COUNTS.items():require(p['slots'][provider]==slots(provider) and len(p['slots'][provider])==n,'outside ninety changed-task validation coordinates')
 require(all(s['cohort']=='validation' for ss in p['slots'].values() for s in ss),'main calls prohibited');check();return p

def identity():
 require(os.environ.get('GITHUB_REPOSITORY')=='agrawal-priyank/depfailbench' and os.environ.get('GITHUB_REF')=='refs/heads/array-revision-linux-validation' and os.environ.get('GITHUB_RUN_ATTEMPT')=='1','original revision-branch workflow required')
 require(bool(os.environ.get('GITHUB_RUN_ID') and os.environ.get('GITHUB_SHA')),'workflow identity absent')
def marker(provider):return BATCH+'-'+provider.lower()+'-prepared'
def prior(provider,path):
 p=plan();identity();require(not path.exists(),'guard exists');q=subprocess.run(['gh','api','--paginate','--slurp','repos/agrawal-priyank/depfailbench/actions/artifacts?per_page=100&name='+marker(provider)],text=True,capture_output=True)
 require(q.returncode==0,'prior artifact inventory unavailable');pages=json.loads(q.stdout);require(pages and all(x['total_count']==0 and not x['artifacts'] for x in pages),'batch already prepared; recover preserved evidence, do not redispatch')
 path.parent.mkdir(parents=True,exist_ok=True);save_json(path,{'clear':True,'provider':provider,'run':os.environ['GITHUB_RUN_ID'],'commit':os.environ['GITHUB_SHA'],'plan_sha256':sha(PLAN),'at':datetime.now(timezone.utc).isoformat()})
def prepare(provider,state,guard=None,mock=False):
 p=plan();require(provider in COUNTS and not state.exists(),'wrong provider or existing evidence')
 if not mock:
  identity();require(os.environ.get('CONFIRM_AMENDED_PROMPT_CHECKS')=='true','explicit paid check confirmation required');require(guard is not None and guard.is_file(),'prior guard required');g=load(guard)
  require(g['clear'] is True and g['provider']==provider and g['run']==os.environ['GITHUB_RUN_ID'] and g['commit']==os.environ['GITHUB_SHA'] and g['plan_sha256']==sha(PLAN),'guard identity differs');require(0<=(datetime.now(timezone.utc)-datetime.fromisoformat(g['at'])).total_seconds()<=3600,'guard expired')
 root=state/'candidate_repo/expanded_study';shutil.copytree(assets_root(),root);shutil.copyfile(ROOT/'requirements.lock',root.parent/'requirements.lock');check(root)
 permission={'schema_version':1,'execution_mode':'mock_validation' if mock else 'live','mock_validation_authorized':mock,'paid_execution_authorized':not mock,'cohort':'validation','authorized_by':'Priyank Agrawal' if not mock else 'synthetic rehearsal','authorization_record':p['authorization_record'],'maximum_cost_usd':CAPS[provider],'expires_at_utc':(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat(),'snapshot':execution_snapshot(root),'token_rates':p['token_rates'],'allowed_providers':[provider],'allowed_artifact_ids':[s['artifact_id'] for s in slots(provider,root)]}
 save_json(state/'reviewed_plan.json',p);save_json(state/'execution_permission.json',permission);permit=ExecutionPermit(state/'execution_permission.json',root=root);SpendingLedger(state/'spending.sqlite',limit_usd=CAPS[provider],simulation_only=False,authorization=permit)
 save_json(state/'run_manifest.json',{'provider':provider,'batch_id':BATCH,'github_run_id':os.environ.get('GITHUB_RUN_ID'),'github_commit':os.environ.get('GITHUB_SHA'),'slots':slots(provider,root),'expected_responses':COUNTS[provider],'cohort':'validation','excluded_from_main':True,'synthetic_data':mock,'plan_sha256':sha(PLAN),'model_settings_unchanged':True,'no_automatic_main_follow_on':True})
 return {'prepared':True,'provider':provider,'excluded_responses':COUNTS[provider],'model_calls':0}
def context(provider,state):
 p=plan();m=load(state/'run_manifest.json');root=state/'candidate_repo/expanded_study';require(load(state/'reviewed_plan.json')==p and m['plan_sha256']==sha(PLAN) and m['provider']==provider and m['slots']==slots(provider,root),'prepared scope differs')
 permit=ExecutionPermit(state/'execution_permission.json',root=root);require(permit.document['allowed_providers']==[provider] and permit.document['allowed_artifact_ids']==[s['artifact_id'] for s in m['slots']],'permission scope differs');require(m['synthetic_data']==(permit.document['execution_mode']=='mock_validation'),'mock/live mismatch')
 if not m['synthetic_data']:
  identity();require(os.environ.get('CONFIRM_AMENDED_PROMPT_CHECKS')=='true' and m['github_run_id']==os.environ['GITHUB_RUN_ID'] and m['github_commit']==os.environ['GITHUB_SHA'],'live workflow differs')
 ledger=SpendingLedger(state/'spending.sqlite',limit_usd=CAPS[provider],simulation_only=False,authorization=permit);return p,m,root,permit,ledger
async def pair(provider,state,index,wire=None,key=None):
 p,m,root,permit,ledger=context(provider,state);require(type(index) is int and 0<=index<COUNTS[provider]//2,'pair outside scope');require(not(state/f'pair_{index:02d}.json').exists(),'completed pair retained; do not repeat')
 for i in range(index):require((state/f'pair_{i:02d}.json').exists(),'unfilled predecessor; review first')
 selected=m['slots'][index*2:index*2+2]
 for s in selected:require(not(state/'artifacts'/s['artifact_id']).exists(),'attempt/output exists; inspect without automatic replacement')
 if m['synthetic_data']:require(type(wire) is httpx.MockTransport and callable(key),'mock transport and credential required')
 else:require(wire is None and key is None,'live state cannot substitute mocks')
 def credential(requested):
  require(requested==provider,'wrong credential scope');v=os.environ.get('AMENDMENT_PROVIDER_API_KEY');require(isinstance(v,str) and bool(v) and not any(c in v for c in '\r\n'),'provider secret missing or invalid');return v
 class Scoped(LiveGenerator):
  def authorize_slot(self,s):require(s in selected and s['provider']==provider and s['cohort']=='validation','outside exact validation pair');super().authorize_slot(s)
 rates={n:TokenRates(**v) for n,v in p['token_rates'].items()}
 async with Scoped(output=state/'artifacts',ledger=ledger,rates=rates,authorization=permit,root=root,wire_transport=wire,credential_loader=key or credential) as sender:
  results=await asyncio.gather(*(sender.generate(s,allowance_usd=p['per_request_allowance_usd'][s['model_id']]) for s in selected),return_exceptions=True)
 require(not any(isinstance(x,BaseException) for x in results),'pair paused; preserve attempts and do not reissue automatically')
 rows=[{k:x[k] for k in ['artifact_id','generation_status','estimated_token_cost_usd']} for x in results];save_json(state/f'pair_{index:02d}.json',rows);return rows

def summarize(provider,state):
 p,m,root,permit,ledger=context(provider,state);require({x.name for x in (state/'artifacts').iterdir()}=={s['artifact_id'] for s in m['slots']},'incomplete/extraneous response set');configs={c['id']:c for c in load(root/'study.json')['configurations']};rows=[]
 for s in m['slots']:
  directory=state/'artifacts'/s['artifact_id']
  if m['synthetic_data']:
   # Mocking the authenticated sender retains live-sender provenance; it is
   # intentionally not admissible as real collected measurement evidence.
   metadata=load(directory/'metadata.json');require(metadata['synthetic_data'] is True and metadata['simulation_only'] is False,'incorrect mock provenance')
   require(all(metadata.get(k)==v for k,v in s.items()),'mock coordinates differ')
   require((directory/'prompt.txt').read_bytes()==(root/'prompts'/f"{s['task']}_{s['condition']}.md").read_bytes(),'mock prompt differs')
   require(metadata['generation_settings']==configs[s['configuration_id']]['generation_settings'] and sha(directory/'app.py')==metadata['source_sha256'],'mock source/configuration differs')
  else:
   v=artifact_manifest(directory,s,configs[s['configuration_id']],root);require(v['synthetic_data'] is False,'synthetic responses forbidden in live batch');metadata=v['metadata']
  rows.append({k:metadata[k] for k in ['artifact_id','generation_status','estimated_token_cost_usd']})
 budget=ledger.snapshot();require(not budget['held'] and not budget['pauses'] and all(a['state']=='settled' for a in budget['attempts']),'unsettled usage/financial pause prevents completion')
 result={'complete':True,'provider':provider,'programs':COUNTS[provider],'cohort':'validation','excluded_from_main':True,'synthetic_data':m['synthetic_data'],'estimated_token_cost_usd':str(Decimal(budget['cost'])/Decimal(budget['units_per_usd'])),'invoice_cost_verified':False,'rows':rows,'ledger':budget};save_json(state/'summary.json',result);return {k:v for k,v in result.items() if k not in ['rows','ledger']}
async def mock(provider,state):
 prepare(provider,state,mock=True);calls=[];canary='SYNTHETIC-AMENDMENT-CANARY-NOT-A-KEY'
 def handler(request):
  b=json.loads(request.content);model=b.get('model', 'gemini-3.8-flash');calls.append(b);return httpx.Response(200,headers={'content-type':'text/event-stream'},content=sse_bytes(stream_events(provider,fixture(provider,model))),request=request)
 for i in range(COUNTS[provider]//2):await pair(provider,state,i,httpx.MockTransport(handler),lambda p:canary)
 try:await pair(provider,state,0,httpx.MockTransport(handler),lambda p:canary)
 except DispatchPaused:pass
 else:raise AssertionError('duplicate dispatch allowed')
 require(len(calls)==COUNTS[provider],'unexpected mock request count')
 require(all(canary.encode() not in f.read_bytes() for f in state.rglob('*') if f.is_file()),'canary persisted')
 return {**summarize(provider,state),'duplicate_blocked':True,'credential_canary_absent':True,'mock_requests':len(calls)}
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('mode',choices=['check','prior','prepare','pair','summarize','mock']);a.add_argument('--provider',choices=list(COUNTS),required=True);a.add_argument('--state',type=Path,required=True);a.add_argument('--guard',type=Path);a.add_argument('--index',type=int);x=a.parse_args()
 try:
  if x.mode=='check':plan();r={'passed':True,'model_calls':0}
  elif x.mode=='prior':prior(x.provider,x.state);r={'clear':True,'model_calls':0}
  elif x.mode=='prepare':r=prepare(x.provider,x.state,x.guard)
  elif x.mode=='pair':r=asyncio.run(pair(x.provider,x.state,x.index))
  elif x.mode=='mock':r=asyncio.run(mock(x.provider,x.state))
  else:r=summarize(x.provider,x.state)
  print(json.dumps(r),flush=True)
 except Exception as e:print(json.dumps({'stopped':True,'error_type':type(e).__name__,'requires_review':True}),flush=True);raise SystemExit(1) from None
