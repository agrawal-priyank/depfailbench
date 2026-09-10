"""Prespecified fixed-task analysis; NumPy is an analysis-only dependency."""
import argparse,json,math
from pathlib import Path
from statistics import NormalDist
import numpy as np

TASKS=['T1','T2','T4','T5']

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
    p=argparse.ArgumentParser();p.add_argument('root');a=p.parse_args();root=Path(a.root)
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
