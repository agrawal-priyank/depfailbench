"""Frozen main scope, single-block stop and protected original responses."""
import importlib.util,json
from pathlib import Path
from copy import deepcopy
import httpx,pytest
from benchmark.expanded.planning import assets_root,allocation
from benchmark.expanded.provider_dry_run import fixture,stream_events,sse_bytes
from benchmark.expanded.spending import DispatchPaused
ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('mistral_main_scope',ROOT/'scripts/mistral_main_first_block.py');main=importlib.util.module_from_spec(spec);spec.loader.exec_module(main)

def test_frozen_science_matches_reviewed_draft_and_prefix_is_balanced():
    old=main.load(assets_root()/'study.json');new=main.frozen_study(old)
    assert all(new[k] is True for k in ['frozen','budget_authorized','paid_execution_authorized'])
    for key in ['frozen','budget_authorized','paid_execution_authorized','status']:new[key]=old[key]
    assert new==old
    slots=main.load_plan()['slots'];assert slots==allocation()[0][:10]
    assert {s['provider'] for s in slots}=={'Mistral'} and sum(s['condition']=='C0' for s in slots)==5

@pytest.mark.parametrize('key,value',[('author_approved',False),('maximum_cost_usd','45'),('per_request_allowance_usd','1'),('slots',[]),('snapshot',{}),('driver_sha256','changed'),('frozen_study_sha256','wrong')])
def test_changed_scope_or_permission_fails_before_any_credential(tmp_path,monkeypatch,key,value):
    p=main.load(main.PLAN);p[key]=value;f=tmp_path/'plan.json';f.write_text(json.dumps(p));monkeypatch.setattr(main,'PLAN',f)
    with pytest.raises(DispatchPaused):main.load_plan()

def test_existing_main_preparation_not_overwritten(tmp_path):
    state=tmp_path/'state';state.mkdir();(state/'original').write_text('preserve')
    with pytest.raises(DispatchPaused):main.prepare(state,mock=True)
    assert (state/'original').read_text()=='preserve'

async def test_all_ten_mocked_main_outputs_in_frozen_order_and_no_duplicates(tmp_path):
    state=tmp_path/'state';main.prepare(state,mock=True);calls=[];canary='MOCK-MISTRAL-NOT-A-REAL-CREDENTIAL'
    def handler(request):
        assert request.headers['authorization']=='Bearer '+canary
        b=json.loads(request.content);assert b['model']=='ministral-3b-2512' and b['temperature']==.7 and b['top_p']==1.0
        calls.append(b['messages'][0]['content'])
        return httpx.Response(200,headers={'content-type':'text/event-stream'},content=sse_bytes(stream_events('Mistral',fixture('Mistral','ministral-3b-2512'))),request=request)
    wire=httpx.MockTransport(handler)
    for i in range(10):
        r=await main.generate(state,i,mock_transport=wire,mock_credential=lambda p:canary)
        assert r['synthetic_data'] and r['cohort']=='main' and r['included_in_main']
        with pytest.raises(DispatchPaused):await main.generate(state,i,mock_transport=wire,mock_credential=lambda p:canary)
    slots=main.load_plan()['slots'];assert calls==[(assets_root()/'prompts'/f"{s['task']}_{s['condition']}.md").read_text() for s in slots]
    assert len(calls)==10 and len(list((state/'artifacts').iterdir()))==10
    assert all(canary.encode() not in p.read_bytes() for p in state.rglob('*') if p.is_file())

async def test_no_skipping_unfilled_scheduled_predecessor(tmp_path):
    state=tmp_path/'state';main.prepare(state,mock=True)
    wire=httpx.MockTransport(lambda r:pytest.fail('must stop before wire'))
    with pytest.raises(DispatchPaused):await main.generate(state,1,mock_transport=wire,mock_credential=lambda p:'mock')

@pytest.mark.parametrize('index',[-1,10,None,True])
async def test_no_extra_main_or_other_provider_coordinate(tmp_path,index):
    with pytest.raises(DispatchPaused):await main.generate(tmp_path/'absent',index)

async def test_mock_state_cannot_load_real_credentials(tmp_path):
    state=tmp_path/'state';main.prepare(state,mock=True)
    with pytest.raises(DispatchPaused):await main.generate(state,0)

def test_live_prepare_requires_workflow_guard_without_creating_state(tmp_path,monkeypatch):
    monkeypatch.delenv('GITHUB_REPOSITORY',raising=False)
    with pytest.raises(DispatchPaused):main.prepare(tmp_path/'state')
    assert not(tmp_path/'state').exists()

def test_workflow_scope_keys_and_stable_marker():
    text=(ROOT/'.github/workflows/full-study.yml').read_text();job=text.split('  mistral-main-first-block:',1)[1]
    keyed=[s for s in job.split('      - ') if 'secrets.MISTRAL_API_KEY' in s]
    assert len(keyed)==10 and all(f'--index {i}' in keyed[i] for i in range(10))
    assert all(s not in job for s in ['secrets.OPENAI_API_KEY','secrets.ANTHROPIC_API_KEY','secrets.GEMINI_API_KEY','secrets.GROK_API_KEY'])
    token=[s for s in job.split('      - ') if 'GH_TOKEN:' in s];assert len(token)==1 and ' prior-run-check ' in token[0]
    assert job.index('Preserve stable first-main marker')<job.index('Generate main scheduled output 0')
    assert "github.run_attempt == '1'" in job and 'continue-on-error' not in job
    assert 'inputs.confirm_paid_generation && inputs.verify_setup_only' in job
    assert text.count('main-mistral-first-${{ github.run_id }}-after-')==10
