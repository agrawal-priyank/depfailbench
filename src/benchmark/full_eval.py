"""Subprocess-isolated full-study evaluation; no provider calls."""
from __future__ import annotations
import argparse,asyncio,hashlib,importlib.util,json,random,time,sys
from pathlib import Path
import httpx
from benchmark.fixtures.common import AppSettings
from benchmark.runner import run_probe
from benchmark.scenarios import T1_SCENARIOS,T4_SCENARIOS
from benchmark.full_tasks import Dependency,SCENARIOS,SAFE,KEY,CONTENT,classify
from benchmark.metrics import SAFE_FAILURE_ACCEPTED
from benchmark.timeout_guard import evaluate_timeout_guard


def evaluation_seed(artifact_id: str, probe: str) -> int:
    """Return a stable seed for generated jitter and other PRNG use."""
    payload=f'depfailbench-evaluation-v1\0{artifact_id}\0{probe}'.encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], 'big')

async def probe_new(task,scenario,factory):
    cfg=AppSettings();dep=Dependency(task,scenario);app=factory(dep,cfg)
    status=body=error=None;elapsed=0
    try:
        async with app.router.lifespan_context(app):
            start=time.perf_counter()
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
                    if task=='T2':response=await asyncio.wait_for(c.get('/catalog'),cfg.deadline_s)
                    else:response=await asyncio.wait_for(c.post('/uploads/'+KEY,json={'content':CONTENT.decode()}),cfg.deadline_s)
                status=response.status_code
                try:body=response.json()
                except ValueError:body=response.text
            finally:elapsed=time.perf_counter()-start
    except Exception as exc:error=f'{type(exc).__name__}: {exc}'
    # Dependency time is simulated while application/backoff time is measured.
    # Their sum is the observable end-to-end latency for deadline enforcement.
    wall_elapsed=elapsed;effective_elapsed=wall_elapsed+dep.virtual_time_s
    deadline=effective_elapsed>cfg.deadline_s
    outcome=classify(task,scenario,status,body,error,deadline,dep)
    notes=sorted(set(dep.contract_violations))
    logical_operations=len({a['operation'] for a in dep.attempts if a.get('request_valid',True)}) or 1
    return {'scenario':scenario,'outcome_class':outcome,'response_status':status,'response_json':body,'unhandled_exception':error,'latency_s':wall_elapsed,'wall_latency_s':wall_elapsed,'virtual_dependency_time_s':dep.virtual_time_s,'effective_latency_s':effective_elapsed,'attempts':dep.attempts,'deadline_violated':deadline,'side_effects':dep.writes,'final_state':{k:v.decode(errors='replace') for k,v in dep.objects.items()},'duplicate_side_effects':0,'retry_amplification_factor':len(dep.attempts)/logical_operations,'notes':notes}

async def evaluate(directory):
    directory=Path(directory);m=json.loads((directory/'metadata.json').read_text());task=m['task']
    result={'artifact_id':m['artifact_id'],'task':task,'condition':m['condition'],'model':m['model_provider'],'clean_qualified':False,'primary_pass':False,'observations':[],'timeout_guard':None,'metadata':m}
    raw=json.loads((directory/'raw_response.json').read_text())
    if raw.get('stop_reason')=='max_tokens' or raw.get('status')=='incomplete':
        result['error']='provider_output_truncated';return result
    try:
        scenarios=list(T1_SCENARIOS if task=='T1' else T4_SCENARIOS if task=='T4' else SCENARIOS[task])
        for scenario in scenarios:
            seed=evaluation_seed(m['artifact_id'],scenario)
            random.seed(seed)
            # Reload the generated module for every probe so module-level state
            # cannot leak from an earlier scenario into a later one.
            module_name=f'full_generated_{scenario}'
            sys.modules.pop(module_name,None)
            spec=importlib.util.spec_from_file_location(module_name,directory/'app.py');module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module);factory=module.create_app
            if task in {'T1','T4'}:
                row=(await run_probe(task,m['artifact_id'],scenario,factory,condition=m['condition'])).to_dict()
                # Explicit full-study interface: validate public receipt and committed ID.
                if task=='T4':
                    body=row['response_json'];state=row['final_state'];effects=row['side_effects']
                    if row['outcome_class']=='resilient_success':
                        valid=isinstance(body,dict) and body.get('order_id')=='order-1' and body.get('status')=='PAID' and len(effects)==1 and body.get('charge_id')==effects[0]['charge_id'] and state.get('charge_id')==effects[0]['charge_id']
                        if not valid:row['outcome_class']='unsafe_failure';row['notes'].append('invalid public payment receipt or charge identity')
                    if state.get('status') not in {'PAID','FAILED','UNPAID','UNRESOLVED','PENDING'}:
                        row['outcome_class']='unsafe_failure';row['notes'].append('violates visible full-study state vocabulary')
            else:row=await probe_new(task,scenario,factory)
            row['evaluation_seed']=seed
            result['observations'].append(row)
            if scenario=='clean':
                result['clean_qualified']=row['outcome_class']=='resilient_success'
                if not result['clean_qualified']:break
        guard_required=task in {'T2','T5'} or m['condition']=='C1'
        if result['clean_qualified'] and guard_required:
            seed=evaluation_seed(m['artifact_id'],'timeout_guard')
            random.seed(seed)
            module_name='full_generated_timeout_guard'
            sys.modules.pop(module_name,None)
            spec=importlib.util.spec_from_file_location(module_name,directory/'app.py');module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
            result['timeout_guard']=await evaluate_timeout_guard(task,module.create_app)
            result['timeout_guard']['evaluation_seed']=seed
        def passed(row):
            safe=(task,row['scenario']) in SAFE_FAILURE_ACCEPTED if task in {'T1','T4'} else row['scenario'] in SAFE
            return row['outcome_class']=='resilient_success' or (safe and row['outcome_class']=='safe_failure')
        guard_pass=not guard_required or bool(result['timeout_guard'] and result['timeout_guard']['pass'])
        result['primary_pass']=result['clean_qualified'] and len(result['observations'])==len(scenarios) and all(passed(x) for x in result['observations']) and guard_pass
    except Exception as exc:result['error']=f'{type(exc).__name__}: {exc}'
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('artifact');p.add_argument('output');a=p.parse_args()
    Path(a.output).write_text(json.dumps(asyncio.run(evaluate(a.artifact)),indent=2))
