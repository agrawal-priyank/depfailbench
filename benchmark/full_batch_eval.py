"""Run each generated artifact in a fresh process with a hard time limit."""
import argparse,json,os,subprocess,sys
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default='full_results');p.add_argument('--repetitions',type=int,default=3);a=p.parse_args();root=Path(a.root)
    # This stage should run in a separate credential-free job; also filter env.
    env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ['KEY','TOKEN','SECRET','CREDENTIAL'])}
    for directory in sorted((root/'artifacts').iterdir()):
        for repeat in range(1,a.repetitions+1):
            out=root/f'evaluation{repeat}'/f'{directory.name}.json';out.parent.mkdir(exist_ok=True)
            if out.exists():continue
            try:
                proc=subprocess.run([sys.executable,'-m','benchmark.full_eval',str(directory),str(out)],env=env,capture_output=True,timeout=45)
                if not out.exists():raise RuntimeError(f'evaluation process exit {proc.returncode}')
            except Exception as exc:
                meta=json.loads((directory/'metadata.json').read_text());out.write_text(json.dumps({'artifact_id':directory.name,'task':meta['task'],'condition':meta['condition'],'model':meta['model_provider'],'metadata':meta,'error':str(exc),'clean_qualified':False,'primary_pass':False,'observations':[]}))
        print('evaluated',directory.name,flush=True)
if __name__=='__main__':main()
