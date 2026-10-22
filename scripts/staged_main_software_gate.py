"""Record or verify an exact offline Linux gate before any fresh paid request."""
import argparse,json,os,subprocess
from pathlib import Path
import xml.etree.ElementTree as ET
from benchmark.expanded.collect import environment,implementation_manifest
from benchmark.expanded.planning import digest
from evaluate_saved_openai_validation import extract_checked
from staged_main_first_gate import plan,sha,PLAN,FROZEN,ROOT,identity


def load(p):return json.loads(Path(p).read_text())
def save(p,d):
    Path(p).parent.mkdir(parents=True,exist_ok=True)
    with Path(p).open('x') as f:f.write(json.dumps(d,indent=2)+'\n')


def validate_report(base,p):
    suite=ET.parse(base/'tests.junit.xml').getroot().find('testsuite')
    assert int(suite.attrib['tests'])==p['expected_software_tests']
    assert all(int(suite.attrib[k])==0 for k in ['failures','errors','skipped'])
    report=load(base/'software_gate.json')
    assert report['plan_sha256']==sha(PLAN) and report['frozen_study_sha256']==sha(FROZEN)
    assert report['snapshot']==p['snapshot'] and report['implementation']==implementation_manifest()
    assert report['environment']['platform'].startswith('Linux-') and report['environment']['python'].startswith('3.12.14')
    assert report['model_api_calls']==0 and report['model_generated_program_executions']==0
    assert report['bench_authored_controls_only'] is True
    return report


def record(output):
    p=plan();identity()
    save(output/'software_gate.json',{'plan_sha256':sha(PLAN),'frozen_study_sha256':sha(FROZEN),
        'snapshot':p['snapshot'],'implementation':implementation_manifest(),'environment':environment(),
        'github_run_id':os.environ['GITHUB_RUN_ID'],'github_commit':os.environ['GITHUB_SHA'],
        'model_api_calls':0,'model_generated_program_executions':0,'bench_authored_controls_only':True})
    validate_report(output,p)


def verify(run_id,output):
    p=plan();identity();assert run_id.isdigit() and int(run_id)>0 and run_id!=os.environ['GITHUB_RUN_ID']
    api='repos/agrawal-priyank/depfailbench/'
    def get(path):return json.loads(subprocess.run(['gh','api',api+path],capture_output=True,check=True).stdout)
    run=get('actions/runs/'+run_id);assert run['head_sha']==os.environ['GITHUB_SHA'] and run['conclusion']=='success'
    jobs=get('actions/runs/'+run_id+'/jobs?per_page=100')['jobs']
    assert len([j for j in jobs if j['name']=='fresh-main-software-gate' and j['conclusion']=='success'])==1
    assert all(j['conclusion']=='skipped' for j in jobs if j['name']!='fresh-main-software-gate')
    name='fresh-main-software-'+run_id
    found=[a for a in get('actions/runs/'+run_id+'/artifacts?per_page=100')['artifacts'] if a['name']==name]
    assert len(found)==1 and not found[0]['expired'];meta=get('actions/artifacts/'+str(found[0]['id']))
    assert meta['workflow_run']['id']==int(run_id) and meta['workflow_run']['head_sha']==os.environ['GITHUB_SHA']
    output.mkdir(parents=True,exist_ok=False);archive=output/'verified_gate.zip';save(output/'verified_gate.metadata.json',meta)
    with archive.open('xb') as f:subprocess.run(['gh','api',api+'actions/artifacts/'+str(meta['id'])+'/zip'],stdout=f,check=True)
    assert meta['digest']=='sha256:'+digest(archive) and meta['size_in_bytes']==archive.stat().st_size
    extract_checked(archive,output/'verified_gate')
    report=validate_report(output/'verified_gate',p)
    assert report['github_run_id']==run_id and report['github_commit']==os.environ['GITHUB_SHA']
    assert report['environment']==environment(),'Installed runtime differs from the tested Linux runtime'
    save(output/'verified_gate_receipt.json',{'passed':True,'verified_run_id':int(run_id),'archive_sha256':digest(archive),
        'plan_sha256':sha(PLAN),'model_api_calls':0,'model_generated_program_executions':0})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['record','verify'])
    p.add_argument('--output',type=Path,required=True);p.add_argument('--run-id');a=p.parse_args()
    if a.mode=='record':record(a.output)
    else:verify(a.run_id,a.output)
