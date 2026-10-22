"""Fresh first-gate scope, frozen settings, budget offsets and credential isolation."""
import importlib.util,json,re,sys
from copy import deepcopy
from pathlib import Path
import httpx,pytest
from benchmark.expanded.planning import allocation,assets_root
from benchmark.expanded.spending import DispatchPaused
from benchmark.expanded.evaluate import probe

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import staged_main_first_gate as driver
import evaluate_staged_main_first_gate as saved


def test_all_first_blocks_are_balanced_main_prefixes_with_unchanged_settings():
    p=driver.plan();assert sum(len(s) for s in p['slots'].values())==40
    for provider,slots in p['slots'].items():
        assert slots==[s for s in allocation()[0] if s['provider']==provider][:10]
        assert all(s['cohort']=='main' for s in slots) and sum(s['condition']=='C0' for s in slots)==5
    assert len({s['artifact_id'] for rows in p['slots'].values() for s in rows})==40
    assert driver.frozen_study()['configurations']==driver.load(assets_root()/'study.json')['configurations']


@pytest.mark.parametrize('provider',driver.PROVIDERS)
async def test_offline_first_ten_do_not_use_real_keys_or_allow_repetition(tmp_path,provider):
    state=tmp_path/provider;report=await driver.mock(provider,state)
    assert report['synthetic_data'] and report['cohort']=='main' and report['programs']==report['mock_requests']==10
    assert report['no_automatic_continuation'] and report['credential_canary_absent']
    assert len(list((state/'artifacts').iterdir()))==10
    with pytest.raises(DispatchPaused):
        await driver.pair(provider,state,0,httpx.MockTransport(lambda r:pytest.fail('duplicate wire call')),lambda p:'canary')


@pytest.mark.parametrize('key,value',[
    ('author_approved',False),('stage','all4320'),('automatic_continuation',True),
    ('driver_sha256','changed'),('snapshot',{}),('frozen_study_sha256','changed'),
    ('evaluation_driver_sha256','changed'),('workflow_sha256','changed'),
    ('cumulative_caps_usd',{'Mistral':'45'}),('prior_current_envelope_token_estimate_usd',{}),
    ('new_campaign_caps_usd',{'Mistral':'45'}),('slots',{})])
def test_modified_scope_or_accounting_stops_before_credentials(tmp_path,monkeypatch,key,value):
    p=driver.load(driver.PLAN);p[key]=value;path=tmp_path/'bad.json';path.write_text(json.dumps(p))
    monkeypatch.setattr(driver,'PLAN',path)
    with pytest.raises((DispatchPaused,KeyError)):driver.plan()


@pytest.mark.parametrize('index',[-1,5,None,True])
async def test_no_output_after_the_first_block_is_dispatchable(tmp_path,index):
    with pytest.raises(DispatchPaused):await driver.pair('Mistral',tmp_path/'absent',index)


async def test_partial_predecessor_and_existing_attempt_are_not_reissued(tmp_path):
    state=tmp_path/'state';driver.prepare('Mistral',state,mock=True)
    wire=httpx.MockTransport(lambda r:pytest.fail('must stop before any wire request'))
    with pytest.raises(DispatchPaused):await driver.pair('Mistral',state,1,wire,lambda p:'canary')
    first=driver.plan()['slots']['Mistral'][0]['artifact_id'];(state/'artifacts'/first).mkdir(parents=True)
    with pytest.raises(DispatchPaused):await driver.pair('Mistral',state,0,wire,lambda p:'canary')


async def test_mock_state_cannot_load_provider_environment_credentials(tmp_path,monkeypatch):
    state=tmp_path/'state';driver.prepare('Google',state,mock=True)
    monkeypatch.setenv('FRESH_MAIN_PROVIDER_API_KEY','REAL-KEY-MUST-NOT-BE-READ')
    with pytest.raises(DispatchPaused):await driver.pair('Google',state,0)
    assert not(state/'artifacts').exists()


def test_live_prepare_requires_workflow_guard_and_preserves_existing_state(tmp_path,monkeypatch):
    monkeypatch.delenv('GITHUB_REPOSITORY',raising=False)
    with pytest.raises(DispatchPaused):driver.prepare('OpenAI',tmp_path/'new')
    assert not(tmp_path/'new').exists()
    state=tmp_path/'existing';state.mkdir();(state/'retain').write_text('original')
    with pytest.raises(DispatchPaused):driver.prepare('OpenAI',state,mock=True)
    assert (state/'retain').read_text()=='original'


def test_workflow_first_gate_cannot_start_any_legacy_job_or_later_batch():
    text=(ROOT/'.github/workflows/full-study.yml').read_text()
    jobs=re.split(r'^  ([a-z][a-z0-9-]+):\n',text.split('jobs:\n',1)[1],flags=re.M)
    assert len(jobs[1::2])==23
    for i in range(1,len(jobs),2):
        name,body=jobs[i],jobs[i+1];condition=body.split('    runs-on:',1)[0]
        if name.startswith('fresh-main-'):
            assert 'inputs.fresh_main_first_gate' in condition
            assert '!inputs.amended_prompt_checks' in condition and '!inputs.amended_main_readiness' in condition
            if name!='fresh-main-first-generation':
                assert 'secrets[' not in body and 'FRESH_MAIN_PROVIDER_API_KEY' not in body
            else:
                assert body.count('FRESH_MAIN_PROVIDER_API_KEY: ${{ secrets[matrix.secret_name] }}')==5
                assert all(f'--index {i}' in body for i in range(5)) and '--index 5' not in body
                assert body.index('Preserve prepared marker')<body.index('Generate exactly')
        else:assert '!inputs.fresh_main_first_gate' in condition,name
    assert "needs: fresh-main-software-gate" in text
    assert 'fresh_verified_software_run' in text


@pytest.mark.parametrize('task',[f'E{i}' for i in range(1,9)])
def test_known_correct_clean_control_passes_for_every_task(task):
    row=probe(task,'clean');assert row['pass'],row
