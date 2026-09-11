"""Subprocess-isolated full-study evaluation; no provider calls."""
from __future__ import annotations
import argparse,asyncio,importlib.util,json,time,sys
from pathlib import Path
import httpx
from benchmark.fixtures.common import AppSettings
from benchmark.runner import run_probe
from benchmark.scenarios import T1_SCENARIOS,T4_SCENARIOS
from benchmark.full_tasks import Dependency,SCENARIOS,SAFE,KEY,CONTENT,classify
from benchmark.metrics import SAFE_FAILURE_ACCEPTED

async def probe_new(task,scenario,factory):
    dep=Dependency(task,scenario);cfg=AppSettings();app=factory(dep,cfg)
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
    deadline=elapsed>cfg.deadline_s or dep.virtual_time_s>cfg.deadline_s
    outcome=classify(task,scenario,status,body,error,deadline,dep)
    return {'scenario':scenario,'outcome_class':outcome,'response_status':status,'response_json':body,'unhandled_exception':error,'latency_s':elapsed,'attempts':dep.attempts,'deadline_violated':deadline,'side_effects':dep.writes,'final_state':{k:v.decode(errors='replace') for k,v in dep.objects.items()},'duplicate_side_effects':0,'retry_amplification_factor':len(dep.attempts)/(3 if task=='T2' else 1)}

async def evaluate(directory):
    directory=Path(directory);m=json.loads((directory/'metadata.json').read_text());task=m['task']
    result={'artifact_id':m['artifact_id'],'task':task,'condition':m['condition'],'model':m['model_provider'],'clean_qualified':False,'primary_pass':False,'observations':[],'metadata':m}
    raw=json.loads((directory/'raw_response.json').read_text())
    if raw.get('stop_reason')=='max_tokens' or raw.get('status')=='incomplete':
        result['error']='provider_output_truncated';return result
    try:
        spec=importlib.util.spec_from_file_location('full_generated',directory/'app.py');module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module);factory=module.create_app
        scenarios=list(T1_SCENARIOS if task=='T1' else T4_SCENARIOS if task=='T4' else SCENARIOS[task])
        for scenario in scenarios:
            if task in {'T1','T4'}:
                row=(await run_probe(task,m['artifact_id'],scenario,factory)).to_dict()
                # Explicit full-study interface: validate public receipt and committed ID.
                if task=='T4':
                    body=row['response_json'];state=row['final_state'];effects=row['side_effects']
                    if row['outcome_class']=='resilient_success':
                        valid=isinstance(body,dict) and body.get('order_id')=='order-1' and body.get('status')=='PAID' and len(effects)==1 and body.get('charge_id')==effects[0]['charge_id'] and state.get('charge_id')==effects[0]['charge_id']
                        if not valid:row['outcome_class']='unsafe_failure';row['notes'].append('invalid public payment receipt or charge identity')
                    if state.get('status') not in {'PAID','FAILED','UNPAID','UNRESOLVED','PENDING'}:
                        row['outcome_class']='unsafe_failure';row['notes'].append('violates visible full-study state vocabulary')
            else:row=await probe_new(task,scenario,factory)
            result['observations'].append(row)
            if scenario=='clean':
                result['clean_qualified']=row['outcome_class']=='resilient_success'
                if not result['clean_qualified']:break
        def passed(row):
            safe=(task,row['scenario']) in SAFE_FAILURE_ACCEPTED if task in {'T1','T4'} else row['scenario'] in SAFE
            return row['outcome_class']=='resilient_success' or (safe and row['outcome_class']=='safe_failure')
        result['primary_pass']=result['clean_qualified'] and len(result['observations'])==len(scenarios) and all(passed(x) for x in result['observations'])
    except Exception as exc:result['error']=f'{type(exc).__name__}: {exc}'
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('artifact');p.add_argument('output');a=p.parse_args()
    Path(a.output).write_text(json.dumps(asyncio.run(evaluate(a.artifact)),indent=2))
