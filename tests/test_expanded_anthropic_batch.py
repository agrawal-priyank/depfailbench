"""Batch scope, no-call guards and resumability; no real provider credentials."""
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from benchmark.expanded.planning import allocation
from benchmark.expanded.providers import TokenRates
from benchmark.expanded.spending import DispatchPaused

spec = importlib.util.spec_from_file_location('anthropic_batch', Path(__file__).parents[1] / 'scripts/expanded_anthropic_validation.py')
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


@pytest.fixture(autouse=True)
def current_core_mock_plan(tmp_path, monkeypatch):
    # The historical live plan stays immutable. Rehearse batch guards against
    # today's core with a temporary plan; this fixture never permits paid calls.
    plan=json.loads(batch.PLAN_PATH.read_text())
    plan['snapshot']=batch.execution_snapshot()
    path=tmp_path/'mock_reviewed_plan.json'
    path.write_text(json.dumps(plan))
    monkeypatch.setattr(batch,'PLAN_PATH',path)


def test_original_live_plan_blocks_a_changed_measurement_core(monkeypatch):
    monkeypatch.setattr(batch,'PLAN_PATH',batch.SCRIPT.with_name('expanded_anthropic_validation_plan.json'))
    with pytest.raises(DispatchPaused,match='snapshot'):
        batch.load_plan()


@pytest.mark.parametrize('limit', ['0', '-1', '6.01', 'NaN'])
def test_budget_rejected_before_creating_any_state(tmp_path, limit):
    state = tmp_path / 'state'
    with pytest.raises(DispatchPaused): batch.prepare(state, maximum_cost_usd=limit)
    assert not state.exists()


def test_live_preparation_needs_confirmation_and_original_attempt(tmp_path, monkeypatch):
    monkeypatch.delenv('CONFIRM_PAID_GENERATION', raising=False)
    monkeypatch.delenv('GITHUB_RUN_ATTEMPT', raising=False)
    with pytest.raises(DispatchPaused): batch.prepare(tmp_path / 'state', maximum_cost_usd='6', live=True)
    monkeypatch.setenv('CONFIRM_PAID_GENERATION', 'true')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '2')
    with pytest.raises(DispatchPaused): batch.prepare(tmp_path / 'state', maximum_cost_usd='6', live=True)
    assert not (tmp_path / 'state').exists()


async def test_foreign_provider_and_main_slots_blocked_before_credentials(tmp_path):
    state=tmp_path/'state';batch.prepare(state, maximum_cost_usd='6')
    plan, manifest, permit, ledger=batch.context(state); calls=[]
    rates={k:TokenRates(**v) for k,v in plan['token_rates'].items()}
    async with batch.ScopedGenerator(output=state/'artifacts',ledger=ledger,rates=rates,authorization=permit,
            credential_loader=lambda p:calls.append(p),wire_transport=httpx.MockTransport(lambda r:None)) as generator:
        for slot in (next(s for s in allocation()[0] if s['provider']=='Anthropic'),
                     next(s for s in allocation()[1] if s['provider']=='OpenAI')):
            with pytest.raises(DispatchPaused): await generator.generate(slot,allowance_usd='.35')
    assert calls==[] and ledger.snapshot()['attempts']==[]


async def test_complete_sixteen_slot_mock_batch_preserves_keys_and_blocks_duplicate(tmp_path):
    report=await batch.mock_rehearsal(tmp_path/'state')
    assert report['complete'] and report['programs']==16
    assert report['mock_wire_calls']==16 and report['model_generation_calls']==0
    assert report['excluded_from_main'] and report['duplicate_dispatch_blocked'] and report['credential_canary_absent']


async def test_stored_plan_mutation_blocks_before_any_dispatch(tmp_path):
    state=tmp_path/'state';batch.prepare(state,maximum_cost_usd='6')
    p=state/'reviewed_plan.json';d=json.loads(p.read_text());d['slots']=d['slots'][1:];p.write_text(json.dumps(d))
    calls=[]
    with pytest.raises(DispatchPaused):
        await batch.generate_slot(state,0,mock_transport=httpx.MockTransport(lambda r:calls.append(r)),mock_credential=lambda p:'synthetic')
    assert calls==[]


async def test_synthetic_account_check_cannot_contact_real_metadata_endpoint(tmp_path):
    state=tmp_path/'state';batch.prepare(state,maximum_cost_usd='6')
    with pytest.raises(DispatchPaused,match='synthetic'):
        await batch.access_check(state)


async def test_unknown_usage_pauses_following_slot_without_replacing_output(tmp_path):
    state=tmp_path/'state';batch.prepare(state,maximum_cost_usd='6');calls=[]
    def handler(request):
        calls.append(1)
        raw=batch.fixture('Anthropic','claude-sonnet-5-5');raw.pop('usage')
        return httpx.Response(200,json=raw,request=request)
    wire=httpx.MockTransport(handler)
    first=await batch.generate_slot(state,0,mock_transport=wire,mock_credential=lambda p:'synthetic')
    assert first['estimated_token_cost_usd'] is None
    with pytest.raises(DispatchPaused): await batch.generate_slot(state,1,mock_transport=wire,mock_credential=lambda p:'synthetic')
    assert calls==[1]


def test_preparation_cannot_overwrite_an_existing_run(tmp_path):
    state=tmp_path/'state';batch.prepare(state,maximum_cost_usd='6')
    before=(state/'execution_permission.json').read_bytes()
    with pytest.raises(FileExistsError): batch.prepare(state,maximum_cost_usd='6')
    assert (state/'execution_permission.json').read_bytes()==before
