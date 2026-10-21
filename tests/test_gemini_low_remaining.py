"""Exact two-response scope and retained-output controls; every wire is mocked."""
import importlib.util
import json
import sys
from pathlib import Path
import httpx
import pytest
from benchmark.expanded.planning import assets_root
from benchmark.expanded.provider_dry_run import fixture, sse_bytes, stream_events
from benchmark.expanded.spending import DispatchPaused

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('gemini_low_sample_tests', ROOT/'scripts/gemini_low_remaining.py')
sample = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sample)


def test_candidate_changes_only_Gemini_identity_and_thinking():
    original = json.loads((assets_root()/'study.json').read_text())
    candidate = sample.candidate_study(original)
    old = next(c for c in original['configurations'] if c['provider']=='Google')
    new = next(c for c in candidate['configurations'] if c['provider']=='Google')
    assert old['generation_settings']['thinking_level']=='medium'
    new['id']=old['id'];new['generation_settings']['thinking_level']='medium'
    assert candidate==original


@pytest.mark.parametrize('key,value', [('author_approved',False), ('maximum_cost_usd','5'), ('per_request_allowance_usd','1'), ('coordinates',[['E1','C0']]), ('driver_sha256','wrong')])
def test_unapproved_or_changed_scope_fails(tmp_path,monkeypatch,key,value):
    plan=sample.load(sample.PLAN);plan[key]=value;p=tmp_path/'bad.json';p.write_text(json.dumps(plan))
    monkeypatch.setattr(sample,'PLAN',p)
    with pytest.raises(DispatchPaused):sample.load_plan()


def test_prepare_never_overwrites_existing_state(tmp_path):
    state=tmp_path/'existing';state.mkdir();(state/'original').write_text('preserve')
    with pytest.raises(DispatchPaused):sample.prepare(state,mock=True)
    assert (state/'original').read_text()=='preserve'


def test_live_prepare_requires_workflow_and_prior_marker_without_credentials(tmp_path,monkeypatch):
    monkeypatch.delenv('GITHUB_REPOSITORY',raising=False)
    with pytest.raises(DispatchPaused):sample.prepare(tmp_path/'state')
    assert not (tmp_path/'state').exists()


async def test_both_exact_responses_mocked_and_duplicate_attempt_blocked(tmp_path):
    state=tmp_path/'state';sample.prepare(state,mock=True);calls=[]
    canary='SYNTHETIC-GEMINI-CANARY-NOT-A-REAL-KEY'
    def handler(request):
        body=json.loads(request.content)
        assert body['generation_config']=={'max_output_tokens':32000,'thinking_level':'low'}
        assert request.headers['x-goog-api-key']==canary
        calls.append(body['input'])
        return httpx.Response(200,headers={'content-type':'text/event-stream'},content=sse_bytes(stream_events('Google',fixture('Google','gemini-3.8-flash'))),request=request)
    transport=httpx.MockTransport(handler)
    for index in range(14):
        report=await sample.generate(state,index,mock_transport=transport,mock_credential=lambda p:canary)
        assert report['synthetic_data'] and report['generation_status']=='completed' and not report['functional_tests_performed']
        with pytest.raises(DispatchPaused):await sample.generate(state,index,mock_transport=transport,mock_credential=lambda p:canary)
    assert len(calls)==14 and calls==[(assets_root()/('prompts/'+task+'_'+condition+'.md')).read_text() for task,condition in sample.load_plan()['coordinates']]
    assert all(canary.encode() not in p.read_bytes() for p in state.rglob('*') if p.is_file())


@pytest.mark.parametrize('index',[-1,14,None,True])
async def test_no_additional_coordinate_can_dispatch(tmp_path,index):
    with pytest.raises(DispatchPaused):await sample.generate(tmp_path/'absent',index)


async def test_synthetic_state_cannot_use_a_real_transport(tmp_path):
    state=tmp_path/'state';sample.prepare(state,mock=True)
    with pytest.raises(DispatchPaused):await sample.generate(state,0)



def test_scope_is_exact_remaining_fourteen():
    coordinates=sample.load_plan()['coordinates']
    assert len(coordinates)==14 and len({tuple(c) for c in coordinates})==14
    assert {tuple(c) for c in coordinates}=={(f'E{i}',c) for i in range(1,9) for c in ['C0','C1']}-{('E1','C0'),('E5','C1')}

def test_workflow_keys_and_retries():
    text=(ROOT/'.github/workflows/gemini-low-remaining.yml').read_text()
    steps=text.split('      - ')
    keyed=[s for s in steps if 'secrets.GEMINI_API_KEY' in s]
    assert len(keyed)==14 and all(' generate ' in s for s in keyed)
    assert 'continue-on-error' not in text and 'matrix:' not in text
    assert text.index('Preserve stable marker')<text.index('Generate remaining coordinate 0')
    assert "github.run_attempt == '1'" in text
    assert all(k not in text for k in ['secrets.GROK_API_KEY','secrets.OPENAI_API_KEY','secrets.ANTHROPIC_API_KEY'])
