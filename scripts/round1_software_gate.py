"""Require exact offline Linux software evidence before continuing paid calls."""
import argparse,os,xml.etree.ElementTree as ET
from pathlib import Path
from benchmark.expanded.collect import environment,implementation_manifest
from benchmark.expanded.provider_generation import save_json
from continue_main_round1 import plan,PLAN,identity,sha,load,get,fetch_named

def validate(output,p):
    suite=ET.parse(output/'tests.junit.xml').getroot().find('testsuite')
    assert int(suite.attrib['tests'])==p['expected_software_tests']
    assert all(int(suite.attrib[k])==0 for k in ['failures','errors','skipped'])
    r=load(output/'software_gate.json')
    assert r['plan_sha256']==sha(PLAN) and r['environment']['platform'].startswith('Linux-')
    assert r['environment']['python'].startswith('3.12.14') and r['environment']['machine']=='x86_64'
    assert r['implementation']==implementation_manifest() and r['model_api_calls']==r['model_generated_program_executions']==0
    return r

def record(output):
    p,_=plan();identity()
    save_json(output/'software_gate.json',{'plan_sha256':sha(PLAN),'environment':environment(),
        'implementation':implementation_manifest(),'github_run_id':os.environ['GITHUB_RUN_ID'],
        'github_commit':os.environ['GITHUB_SHA'],'model_api_calls':0,'model_generated_program_executions':0})
    validate(output,p)

def verify(run,output):
    p,_=plan();identity();assert run.isdigit() and run!=os.environ['GITHUB_RUN_ID']
    r=get('actions/runs/'+run);assert r['head_sha']==os.environ['GITHUB_SHA'] and r['conclusion']=='success'
    jobs=get('actions/runs/'+run+'/jobs?per_page=100')['jobs']
    assert len([j for j in jobs if j['name']=='round1-software-gate' and j['conclusion']=='success'])==1
    assert all(j['conclusion']=='skipped' for j in jobs if j['name']!='round1-software-gate')
    meta=fetch_named(int(run),os.environ['GITHUB_SHA'],'fresh-main-round1-software-'+run,output)
    report=validate(output/'contents',p)
    assert report['github_run_id']==run and report['github_commit']==os.environ['GITHUB_SHA']
    assert report['environment']==environment(),'Installed runtime differs from Linux gate'
    save_json(output/'receipt.json',{'passed':True,'verified_run_id':int(run),'archive_sha256':sha(output/'archive.zip'),
        'artifact_id':meta['id'],'model_api_calls':0,'generated_program_executions':0})

if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('mode',choices=['record','verify']);q.add_argument('--output',type=Path,required=True);q.add_argument('--run-id');a=q.parse_args()
    if a.mode=='record':record(a.output)
    else:verify(a.run_id,a.output)
