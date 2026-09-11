"""Prespecified fixed-task analysis; NumPy is an analysis-only dependency."""
import argparse,csv,json,math,sysconfig
from pathlib import Path
from statistics import NormalDist
import numpy as np

TASKS=['T1','T2','T4','T5']

def find_schedule(explicit=None):
    candidates=[]
    if explicit:candidates.append(Path(explicit))
    candidates.extend([
        Path(__file__).resolve().parents[2]/'full_study_schedule.csv',
        Path.cwd()/'full_study_schedule.csv',
        Path(sysconfig.get_path('data'))/'share/depfailbench/full_study_schedule.csv',
    ])
    for candidate in candidates:
        if candidate.is_file():return candidate
    raise FileNotFoundError('full_study_schedule.csv not found; pass --schedule PATH')

def validate_evaluation_sets(root,schedule_path):
    with schedule_path.open(newline='',encoding='utf-8') as handle:
        schedule=list(csv.DictReader(handle))
    expected={row['artifact_id']:row for row in schedule}
    if len(schedule)!=320 or len(expected)!=320:
        raise ValueError('Schedule must contain 320 unique artifact IDs')
    expected_files={artifact_id+'.json' for artifact_id in expected}
    for repeat in [1,2,3]:
        directory=root/f'evaluation{repeat}'
        actual_files={path.name for path in directory.glob('*.json')}
        if actual_files!=expected_files:
            missing=sorted(expected_files-actual_files);extra=sorted(actual_files-expected_files)
            raise ValueError(f'evaluation{repeat} does not match schedule: missing={missing[:5]}, extra={extra[:5]}')
        seen=set()
        for path in sorted(directory.glob('*.json')):
            record=json.loads(path.read_text())
            artifact_id=record.get('artifact_id')
            if artifact_id in seen:raise ValueError(f'Duplicate artifact_id in evaluation{repeat}: {artifact_id}')
            seen.add(artifact_id)
            if artifact_id+'.json'!=path.name or artifact_id not in expected:
                raise ValueError(f'Artifact ID/file mismatch in evaluation{repeat}: {path.name}')
            planned=expected[artifact_id]
            provider='OpenAI' if planned['model'].startswith('openai_') else 'Anthropic'
            metadata=record.get('metadata',{})
            observed=(record.get('task'),record.get('condition'),record.get('model'),metadata.get('generation_index'))
            planned_coordinates=(planned['task'],planned['condition'],provider,int(planned['generation_index']))
            if observed!=planned_coordinates:
                raise ValueError(f'Artifact coordinates differ from schedule for {artifact_id}: {observed!r}')

def wilson(k,n,alpha=.05):
    if not n:return [None,None]
    z=NormalDist().inv_cdf(1-alpha/2);p=k/n;d=1+z*z/n
    c=(p+z*z/(2*n))/d;h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return [max(0,c-h),min(1,c+h)]

def model_analysis(rows,seed=20260910,permutations=100000,bootstraps=10000):
    rng=np.random.default_rng(seed);cells={};diff=0.;perm=np.zeros(permutations);boot=np.zeros(bootstraps);lower=upper=0.
    for task in TASKS:
        pair=[];intervals=[]
        for cond in ['C0','C1']:
            rr=[r for r in rows if r['task']==task and r['condition']==cond]
            n=len(rr);k=sum(r['primary_pass'] for r in rr)
            if n!=20:raise ValueError(f'Primary analysis requires 20 present artifacts for {task}/{cond}, got {n}')
            cells[task+':'+cond]={'n':n,'primary_pass':k,'clean_pass':sum(r['clean_qualified'] for r in rr),'primary_rate':k/n,'wilson95':wilson(k,n)}
            pair.append((k,n));intervals.append(wilson(k,n,.05/8))
        (k0,n0),(k1,n1)=pair;observed=k1/n1-k0/n0;diff+=observed/4
        # Exact exchangeable binary-label permutation within each task, sampled via hypergeometric.
        permk=rng.hypergeometric(k0+k1,n0+n1-k0-k1,n1,size=permutations)
        perm+=(permk/n1-(k0+k1-permk)/n0)/4
        boot+=(rng.binomial(n1,k1/n1,size=bootstraps)/n1-rng.binomial(n0,k0/n0,size=bootstraps)/n0)/4
        lower+=(intervals[1][0]-intervals[0][1])/4;upper+=(intervals[1][1]-intervals[0][0])/4
    return {'cells':cells,'risk_difference':diff,'permutation_p':(1+int(np.sum(np.abs(perm)>=abs(diff)-1e-12)))/(permutations+1),'bootstrap95':np.quantile(boot,[.025,.975]).tolist(),'conservative_wilson95':[lower,upper]}

def main():
    p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('--schedule');a=p.parse_args();root=Path(a.root)
    validate_evaluation_sets(root,find_schedule(a.schedule))
    rows=[json.loads(p.read_text()) for p in sorted((root/'evaluation1').glob('*.json'))]
    summary={'artifacts':len(rows),'complete':len(rows)==320,'models':{},'repeat_disagreements':[]}
    def signature(r):return (r['clean_qualified'],r['primary_pass'],[(x['scenario'],x['outcome_class']) for x in r['observations']],r.get('error'))
    for r in rows:
        for repeat in [2,3]:
            p=root/f'evaluation{repeat}'/(r['artifact_id']+'.json')
            if not p.exists() or signature(r)!=signature(json.loads(p.read_text())):summary['repeat_disagreements'].append([r['artifact_id'],repeat])
    if summary['complete'] and not summary['repeat_disagreements']:
        for model in ['OpenAI','Anthropic']:summary['models'][model]=model_analysis([r for r in rows if r['model']==model])
        ranked=sorted(summary['models'],key=lambda m:summary['models'][m]['permutation_p']);previous=0
        for i,m in enumerate(ranked):
            adj=max(previous,min(1,(2-i)*summary['models'][m]['permutation_p']));summary['models'][m]['holm_p']=adj;previous=adj
    else:summary['analysis_note']='Incomplete or nondeterministic: confirmatory statistics withheld.'
    (root/'analysis.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
