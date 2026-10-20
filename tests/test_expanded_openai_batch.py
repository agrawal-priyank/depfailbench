"""Excluded OpenAI batch guards; all HTTP responses here are synthetic."""
import importlib.util
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from benchmark.expanded.planning import allocation
from benchmark.expanded.providers import TokenRates
from benchmark.expanded.spending import DispatchPaused

spec=importlib.util.spec_from_file_location('openai_batch',Path(__file__).parents[1]/'scripts/expanded_openai_validation.py')
batch=importlib.util.module_from_spec(spec);spec.loader.exec_module(batch)


@pytest.mark.parametrize('limit',['0','-1','8.01','NaN','Infinity'])
def test_budget_rejected_without_creating_state(tmp_path,limit):
    with pytest.raises(DispatchPaused):batch.prepare(tmp_path/'state',maximum_cost_usd=limit)
    assert not (tmp_path/'state').exists()


def test_exact_allocation_and_settings():
    plan=batch.load_plan();assert len(plan['slots'])==64
    assert {s['configuration_id'] for s in plan['slots']}=={'gpt_6_1_sol','gpt_6_luna','gpt_6_luna_reasoning_effort_low','gpt_6_luna_reasoning_effort_high'}
    assert len({(s['task'],s['condition']) for s in plan['slots']})==16


def workflow(monkeypatch):
    for k,v in {'CONFIRM_PAID_GENERATION':'true','GITHUB_RUN_ATTEMPT':'1','GITHUB_REPOSITORY':'agrawal-priyank/depfailbench','GITHUB_RUN_ID':'synthetic-run','GITHUB_SHA':'synthetic-sha'}.items():monkeypatch.setenv(k,v)


def guard(tmp_path,monkeypatch,artifacts=(),count=None):
    workflow(monkeypatch)
    page={'artifacts':list(artifacts),'total_count':len(artifacts) if count is None else count}
    monkeypatch.setattr(batch.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout=json.dumps([page])))
    path=tmp_path/'prior_guard.json';batch.prior_run_check(path);return path


def test_live_needs_confirmation_original_attempt_and_prior_check(tmp_path,monkeypatch):
    workflow(monkeypatch)
    with pytest.raises(DispatchPaused,match='prior batch'):batch.prepare(tmp_path/'state',maximum_cost_usd='8',live=True)
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT','2')
    with pytest.raises(DispatchPaused,match='original'):batch.prepare(tmp_path/'state',maximum_cost_usd='8',live=True)
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1');monkeypatch.delenv('CONFIRM_PAID_GENERATION')
    with pytest.raises(DispatchPaused):batch.prepare(tmp_path/'state',maximum_cost_usd='8',live=True)
    assert not (tmp_path/'state').exists()


def test_previous_batch_marker_blocks_even_if_expired(tmp_path,monkeypatch):
    with pytest.raises(DispatchPaused,match='already has saved state'):
        guard(tmp_path,monkeypatch,[{'name':batch.load_plan()['prepared_artifact_name'],'expired':True}])


def test_incomplete_inventory_blocks_and_never_creates_guard(tmp_path,monkeypatch):
    with pytest.raises(DispatchPaused,match='incomplete'):guard(tmp_path,monkeypatch,count=1)
    assert not (tmp_path/'prior_guard.json').exists()


def test_live_guard_binding_and_expiry(tmp_path,monkeypatch):
    path=guard(tmp_path,monkeypatch);batch.validate_prior_run_guard(path)
    d=json.loads(path.read_text());d['checked_at_utc']=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat();path.write_text(json.dumps(d))
    with pytest.raises(DispatchPaused,match='stale'):batch.validate_prior_run_guard(path)
    batch.validate_prior_run_guard(path,check_age=False)
    monkeypatch.setenv('GITHUB_RUN_ID','different-run')
    with pytest.raises(DispatchPaused,match='does not match'):batch.validate_prior_run_guard(path,check_age=False)


async def test_foreign_provider_and_main_block_before_loading_credentials(tmp_path):
    state=tmp_path/'state';batch.prepare(state,maximum_cost_usd='8')
    plan,manifest,permit,ledger=batch.context(state);calls=[]
    rates={k:TokenRates(**v) for k,v in plan['token_rates'].items()}
    async with batch.ScopedGenerator(output=state/'artifacts',ledger=ledger,rates=rates,authorization=permit,
            credential_loader=lambda p:calls.append(p),wire_transport=httpx.MockTransport(lambda r:None)) as generator:
        for slot in (next(s for s in allocation()[0] if s['provider']=='OpenAI'),next(s for s in allocation()[1] if s['provider']=='Anthropic')):
            with pytest.raises(DispatchPaused):await generator.generate(slot,allowance_usd='.35')
    assert calls==[] and ledger.snapshot()['attempts']==[]


async def test_full_64_slot_mock_batch_has_no_paid_calls_or_key_leaks(tmp_path):
    report=await batch.mock_rehearsal(tmp_path/'state')
    assert report['complete'] and report['programs']==64 and report['mock_wire_calls']==64
    assert report['model_generation_calls']==0 and report['excluded_from_main']
    assert report['duplicate_dispatch_blocked'] and report['credential_canary_absent']


async def test_metadata_uses_two_exact_get_endpoints_without_generation(tmp_path):
    state=tmp_path/'state';batch.prepare(state,maximum_cost_usd='8');calls=[]
    def handler(request):
        calls.append((request.method,str(request.url)))
        return httpx.Response(200,json={'id':request.url.path.rsplit('/',1)[-1]},request=request)
    report=await batch.access_check(state,mock_transport=httpx.MockTransport(handler),mock_credential=lambda p:'synthetic')
    assert report['passed'] and report['synthetic_data'] and report['model_generation_calls']==0
    assert calls==[('GET','https://api.openai.com/v1/models/gpt-6-luna'),('GET','https://api.openai.com/v1/models/gpt-6.1-sol')]


async def test_synthetic_account_cannot_call_real_endpoint(tmp_path):
    state=tmp_path/'state';batch.prepare(state,maximum_cost_usd='8')
    with pytest.raises(DispatchPaused,match='synthetic'):await batch.access_check(state)


async def test_unknown_usage_keeps_output_and_pauses_next_slot(tmp_path):
    state=tmp_path/'state';batch.prepare(state,maximum_cost_usd='8');calls=[]
    def handler(request):
        calls.append(1);raw=batch.fixture('OpenAI',json.loads(request.content)['model']);raw.pop('usage')
        return httpx.Response(200,json=raw,request=request)
    wire=httpx.MockTransport(handler)
    first=await batch.generate_slot(state,0,mock_transport=wire,mock_credential=lambda p:'synthetic')
    assert first['estimated_token_cost_usd'] is None
    with pytest.raises(DispatchPaused):await batch.generate_slot(state,1,mock_transport=wire,mock_credential=lambda p:'synthetic')
    assert calls==[1]


async def test_saved_plan_mutation_blocks_dispatch(tmp_path):
    state=tmp_path/'state';batch.prepare(state,maximum_cost_usd='8')
    path=state/'reviewed_plan.json';plan=json.loads(path.read_text());plan['slots']=plan['slots'][1:];path.write_text(json.dumps(plan));calls=[]
    with pytest.raises(DispatchPaused):await batch.generate_slot(state,0,mock_transport=httpx.MockTransport(lambda r:calls.append(r)),mock_credential=lambda p:'synthetic')
    assert calls==[]


def test_existing_state_never_overwritten(tmp_path):
    state=tmp_path/'state';batch.prepare(state,maximum_cost_usd='8');before=(state/'execution_permission.json').read_bytes()
    with pytest.raises(FileExistsError):batch.prepare(state,maximum_cost_usd='8')
    assert before==(state/'execution_permission.json').read_bytes()
