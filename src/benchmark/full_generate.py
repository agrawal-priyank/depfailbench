"""Budget-limited full-study generation. Never executes generated code."""
from __future__ import annotations
import argparse,csv,hashlib,json,os,time
from pathlib import Path
from datetime import datetime,timezone
from benchmark.generate import openai_generate,anthropic_generate,extract_code
from benchmark.prompts import compose_prompt

# Fixed 2026 study accounting rates (USD per million input/output tokens); they are not live provider billing prices.
RATES={'OpenAI':(4.,20.),'Anthropic':(5.,25.)}
LIMIT_OUTPUT=12000

def reservation(prompt,provider):
    # Byte count is a deliberately loose upper bound for text input tokens.
    tokens=len(prompt.encode('utf-8'))+1024
    if tokens>8192:raise ValueError('Prompt exceeds conservative 8192-token guard')
    ip,op=RATES[provider]
    return (tokens*ip+LIMIT_OUTPUT*op)/1e6

def charge(raw,provider):
    usage=raw.get('usage',{});ip,op=RATES[provider]
    if 'input_tokens' not in usage or 'output_tokens' not in usage:return None
    # No caching/batch requested; charge cache tokens at base input price too.
    inp=usage['input_tokens']+usage.get('cache_creation_input_tokens',0)+usage.get('cache_read_input_tokens',0)
    return (inp*ip+usage['output_tokens']*op)/1e6

def load_spend(events):
    # Started calls are retained at the reserved maximum if completion is lost.
    by={}
    for row in events:
        if row['event']=='start':by[row['attempt_id']]=row['reserved']
        if row['event']=='finish':by[row['attempt_id']]=row['charged']
    return sum(by.values())

def main():
    p=argparse.ArgumentParser();p.add_argument('--provider',choices=RATES,required=True);p.add_argument('--cap',type=float,required=True);p.add_argument('--root',default='full_results');p.add_argument('--additional-attempts',type=int,default=0);a=p.parse_args()
    root=Path(a.root);artifacts=root/'artifacts';artifacts.mkdir(parents=True,exist_ok=True)
    ledger=root/f'{a.provider}_ledger.jsonl';events=[json.loads(x) for x in ledger.read_text().splitlines()] if ledger.exists() else []
    def log(row):
        row['at']=datetime.now(timezone.utc).isoformat()
        with ledger.open('a') as f:f.write(json.dumps(row)+'\n');f.flush();os.fsync(f.fileno())
        events.append(row)
    plan=json.loads(Path('generation_plan.json').read_text())
    model_key='openai_gpt56sol' if a.provider=='OpenAI' else 'anthropic_opus5';config=plan['models'][model_key]
    schedule=list(csv.DictReader(open('full_study_schedule.csv')))
    for slot in schedule:
        if slot['model']!=model_key:continue
        target=artifacts/slot['artifact_id']
        if target.exists():
            if all((target/n).exists() for n in ['app.py','metadata.json','raw_response.json','prompt.txt']):continue
            raise RuntimeError('Partial artifact needs audit; refusing overwrite')
        scaffold_root=Path('full_study/scaffolds') if slot['task'] in {'T2','T5'} else Path('scaffolds')
        prompt=compose_prompt(slot['task'],slot['condition'],Path('full_study/prompts'),scaffold_root)
        reserved=reservation(prompt,a.provider)
        prior=sum(e['event']=='start' and e.get('artifact_id')==slot['artifact_id'] for e in events)
        max_attempts=3+a.additional_attempts
        for attempt in range(prior,max_attempts):
            if load_spend(events)+reserved>a.cap:
                log({'event':'budget_stop','artifact_id':slot['artifact_id'],'spent_or_reserved':load_spend(events),'next_reservation':reserved,'cap':a.cap});print('BUDGET STOP',flush=True);return
            attempt_id=f"{slot['artifact_id']}_attempt{attempt+1}"
            log({'event':'start','artifact_id':slot['artifact_id'],'attempt_id':attempt_id,'reserved':reserved})
            try:
                text,raw=(openai_generate if a.provider=='OpenAI' else anthropic_generate)(config,prompt)
            except Exception as exc:
                # Provider failures/ambiguous timeouts conservatively consume reservation.
                log({'event':'operational_error','artifact_id':slot['artifact_id'],'attempt_id':attempt_id,'error':str(exc)[:1200]})
                if any(x in str(exc).lower() for x in ['401','403','credit','balance','workspace','404']):raise
                if attempt==max_attempts-1:raise
                time.sleep(10*(attempt+1));continue
            actual=charge(raw,a.provider)
            if actual is None:actual=reserved
            target.mkdir()
            meta={'artifact_id':slot['artifact_id'],'task':slot['task'],'condition':slot['condition'],'model_provider':a.provider,'model_family':config['family'],'model_version':raw.get('model',config['model_id']),'generation_index':int(slot['generation_index']),'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'generated_at':datetime.now(timezone.utc).isoformat(),'provider_response_id':raw.get('id'),'provider_usage':raw.get('usage'),'scaffold_sha256':hashlib.sha256((scaffold_root/slot['task']/'app.py').read_bytes()).hexdigest(),'dependency_lock_sha256':hashlib.sha256(Path('requirements.lock').read_bytes()).hexdigest(),'temperature':None,'top_p':None}
            (target/'app.py').write_text(extract_code(text or ''))
            (target/'prompt.txt').write_text(prompt)
            (target/'raw_response.json').write_text(json.dumps(raw,indent=2))
            (target/'metadata.json').write_text(json.dumps(meta,indent=2))
            log({'event':'finish','artifact_id':slot['artifact_id'],'attempt_id':attempt_id,'charged':actual,'response_id':raw.get('id')})
            print(slot['artifact_id'],f'cumulative=${load_spend(events):.4f}',flush=True)
            if actual>reserved:raise RuntimeError('Usage exceeded conservative reservation; stop for budget audit')
            break
    print('PROVIDER COMPLETE',a.provider,load_spend(events),flush=True)

if __name__=='__main__':main()
