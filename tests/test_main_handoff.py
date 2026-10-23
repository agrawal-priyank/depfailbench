"""No duplicate dispatch, exact software gate, and durable handoff marker agreement."""
import json,pytest
import continue_main_remaining as gen
import control_main_remaining as control
from benchmark.expanded.spending import DispatchPaused

def test_controller_and_workflow_share_exact_guard_name(monkeypatch):
    text=(gen.ROOT/'.github/workflows/expanded-local-validation.yml').read_text()
    expected=gen.CAMPAIGN+'-handoff-recovery-advance-r${{ inputs.round_id }}'
    assert 'name: '+expected in text
    for r in [5,6]:assert control.marker_name(r)==expected.replace('${{ inputs.round_id }}',str(r))
    assert text.index('Preserve advance intent before dispatch')<text.index('Start next exact-commit round once')

@pytest.mark.parametrize('provider',gen.PROVIDERS)
def test_initial_round5_sources_pin_complete_original_prefix(provider):
    p,_=gen.plan();h=p['handoff_recovery'];s=h['provider_sources'][provider];a=h['provider_audits'][provider]
    assert a['run_id']==39938352224 and a['commit']==h['commit']
    assert s['run_id']==(39929309804 if provider in ['Anthropic','Google'] else 39938352224)
    assert s['artifact_id']>0 and a['artifact_id']>0 and len(s['archive_sha256'])==64

@pytest.mark.parametrize('r',[4,7])
def test_paid_identity_blocks_rounds_outside_remaining_scope(monkeypatch,r):
    p,_=gen.plan();monkeypatch.setenv('GITHUB_REPOSITORY','agrawal-priyank/depfailbench');monkeypatch.setenv('GITHUB_REF','refs/heads/'+p['branch']);monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1');monkeypatch.setenv('GITHUB_RUN_ID','999');monkeypatch.setenv('GITHUB_SHA','fixture');monkeypatch.setenv('REMAINING_ROUND',str(r))
    with pytest.raises(DispatchPaused):gen.identity()

@pytest.mark.parametrize('damage',['none','queued_software','other_failure','round5_exists','wrong_completion_hash'])
def test_handoff_entry_exact_gate_and_no_duplicate_guard(tmp_path,monkeypatch,damage):
    p,_=gen.plan();h=p['handoff_recovery'];software=111;run=999;commit='controlled-fixture-no-dispatch'
    monkeypatch.setattr(control,'identity',lambda:None);monkeypatch.setenv('REMAINING_ROUND','5');monkeypatch.setenv('REMAINING_MODE','paid');monkeypatch.setenv('VERIFIED_SOFTWARE_RUN',str(software));monkeypatch.setenv('GITHUB_SHA',commit);monkeypatch.setenv('GITHUB_RUN_ID',str(run));monkeypatch.setenv('PREVIOUS_ROUND_RUN',str(h['run_id']))
    def get(path):
        if path.startswith('actions/runs?'):return {'workflow_runs':[{'head_sha':h['commit'],'head_branch':h['branch'],'display_title':'Array main upload recovery round 5 (paid)'}] if damage=='round5_exists' else []}
        if '/jobs?' in path:return {'jobs':[{'id':h['failed_job_id'],'name':'other' if damage=='other_failure' else 'completion','conclusion':'failure'}]}
        ident=int(path.split('/')[-1]);old=ident!=software
        return {'status':'queued' if damage=='queued_software' and not old else 'completed','conclusion':'failure' if old else 'success','run_attempt':1,'head_sha':h['commit'] if old else commit,'head_branch':h['branch'] if old else p['branch'],'workflow_id':p['workflow_id']}
    def fetch(run,sha,name,out):
        (out/'contents').mkdir(parents=True)
        if run==software:
            data={'passed':True,'tests':p['expected_software_tests'],'commit':commit,'run_id':software,'attempt':1,'mode':'software','plan_sha256':gen.sha(gen.PLAN),'model_api_calls':0};file=out/'contents/software_gate.json';meta={}
        else:
            data={'passed':True,'round':4,'new_outputs':720,'records':6480,'groups':14,'cumulative_main_outputs':2880,'audits':[{'audit':{'passed':True}}]*14};file=out/'contents/round_completion.json';meta={'id':h['completion']['artifact_id']}
            (out/'archive.zip').write_bytes(b'fixture')
        file.write_text(json.dumps(data));return meta
    realsha=control.sha
    def hash_(path):
        if path.name=='archive.zip':return h['completion']['archive_sha256']
        if path.name=='round_completion.json':return 'wrong' if damage=='wrong_completion_hash' else h['completion_report_sha256']
        return realsha(path)
    monkeypatch.setattr(control,'get',get);monkeypatch.setattr(control,'fetch_named',fetch);monkeypatch.setattr(control,'sha',hash_)
    if damage=='none':control.entry(tmp_path/'entry');assert gen.load(tmp_path/'entry/entry.json')['passed']
    else:
        with pytest.raises(DispatchPaused):control.entry(tmp_path/'entry')
