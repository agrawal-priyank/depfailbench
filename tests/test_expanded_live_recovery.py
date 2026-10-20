"""Authenticated wire, crash recovery and reconciliation tests; all HTTP is mocked."""
import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import httpx
import pytest

from benchmark.expanded.execution_authorization import ExecutionPermit, execution_snapshot
from benchmark.expanded.live_generation import LiveGenerator
from benchmark.expanded.live_transport import AuthenticatedTransport, SECRET_NAMES
from benchmark.expanded.planning import allocation, assets_root
from benchmark.expanded.provider_dry_run import fixture, sse_bytes, stream_events
from benchmark.expanded.provider_generation import OfflineGenerator
from benchmark.expanded.provider_recovery import recover_saved_response
from benchmark.expanded.spending import DispatchPaused, SpendingLedger
from benchmark.expanded.providers import ENDPOINTS, TokenRates

DESIGN=json.loads((assets_root()/'study.json').read_text())
RATES={c['model_id']:TokenRates('2','10','synthetic://not-actual-prices','2026-10-20') for c in DESIGN['configurations']}
SOURCE=json.loads((assets_root()/'provider_fixtures.json').read_text())['source']


def slot(provider):
    return next(s for s in allocation()[1] if s['provider']==provider)


def permit_file(tmp_path, **changes):
    document={'schema_version':1,'execution_mode':'mock_validation','mock_validation_authorized':True,
        'paid_execution_authorized':False,'cohort':'validation',
        'authorized_by':'synthetic test fixture, not actual author approval','authorization_record':'synthetic transport test only',
        'maximum_cost_usd':'10','expires_at_utc':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
        'snapshot':execution_snapshot(),'token_rates':{name:asdict(rate) for name,rate in RATES.items()}}
    document.update(changes)
    p=tmp_path/'synthetic_test_permission.json';p.write_text(json.dumps(document))
    return p


def offline(tmp_path, handler):
    ledger=SpendingLedger(tmp_path/'spend.sqlite',limit_usd='10')
    return OfflineGenerator(output=tmp_path/'artifacts',ledger=ledger,rates=RATES,transport=httpx.MockTransport(handler))


@pytest.mark.parametrize('changes',[
    {'mock_validation_authorized':False},{'paid_execution_authorized':True},{'cohort':'main'},{'maximum_cost_usd':'0'},
    {'authorized_by':''},{'authorization_record':''},
    {'expires_at_utc':'2020-01-01T00:00:00+00:00'}, {'expires_at_utc':'2099-01-01'}, {'snapshot':{}},
])
def test_unreviewed_expired_main_or_changed_permission_is_rejected(tmp_path,changes):
    with pytest.raises((DispatchPaused,ValueError)):
        ExecutionPermit(permit_file(tmp_path,**changes))


async def test_missing_permission_never_reads_a_credential_or_sends_http(tmp_path):
    calls=[]
    def secret(provider):
        calls.append(provider)
        raise AssertionError('credential must not be read')
    ledger=SpendingLedger(tmp_path/'spend.sqlite',limit_usd='10')
    with pytest.raises(DispatchPaused):
        LiveGenerator(output=tmp_path/'artifacts',ledger=ledger,rates=RATES,authorization=None,credential_loader=secret)
    assert calls==[] and ledger.snapshot()['attempts']==[]


@pytest.mark.parametrize('provider',list(ENDPOINTS))
async def test_authenticated_stream_is_exact_and_keys_never_enter_saved_records(tmp_path,provider):
    authorization=ExecutionPermit(permit_file(tmp_path))
    ledger=SpendingLedger(tmp_path/'live.sqlite',limit_usd='10',simulation_only=False,authorization=authorization)
    canary='SYNTHETIC-SECRET-CANARY-NOT-A-REAL-KEY'
    calls=[]
    def handler(request):
        calls.append(request)
        header='x-api-key' if provider=='Anthropic' else 'x-goog-api-key' if provider=='Google' else 'authorization'
        assert request.headers[header]==(canary if provider in {'Anthropic','Google'} else 'Bearer '+canary)
        body=json.loads(request.content)
        assert str(request.url)==ENDPOINTS[provider][1]
        return httpx.Response(200,headers={'content-type':'text/event-stream'},
            content=sse_bytes(stream_events(provider,fixture(provider,body['model']))),request=request)
    async with LiveGenerator(output=tmp_path/'artifacts',ledger=ledger,rates=RATES,authorization=authorization,
            credential_loader=lambda p:canary,wire_transport=httpx.MockTransport(handler)) as generator:
        s=slot(provider);row=await generator.generate(s,allowance_usd='.01')
        assert row['generation_status']=='completed' and row['synthetic_data']
        assert not row['simulation_only']  # live-ledger control tested through synthetic wire
        with pytest.raises(DispatchPaused,match='exists'):
            await generator.generate(s,allowance_usd='.01')
        with pytest.raises(DispatchPaused,match='cohort'):
            await generator.generate(next(x for x in allocation()[0] if x['provider']==provider),allowance_usd='.01')
    assert len(calls)==1
    for f in (tmp_path/'artifacts').rglob('*'):
        if f.is_file():assert canary.encode() not in f.read_bytes()


async def test_transport_blocks_redirect_destinations_before_loading_keys(tmp_path):
    authorization=ExecutionPermit(permit_file(tmp_path));calls=[]
    transport=AuthenticatedTransport(permit=authorization,credential_loader=lambda p:calls.append(p),
        wire_transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(AssertionError('no HTTP'))))
    async with httpx.AsyncClient(transport=transport,follow_redirects=False) as client:
        for url in ('http://api.openai.com/v1/responses','https://example.com/v1/responses','https://api.openai.com/v1/responses?key=x'):
            with pytest.raises(DispatchPaused,match='endpoint'):
                await client.post(url,json={})
    assert calls==[]


async def test_changed_permission_or_rates_prevents_reservation_and_credentials(tmp_path):
    p=permit_file(tmp_path);authorization=ExecutionPermit(p)
    ledger=SpendingLedger(tmp_path/'live.sqlite',limit_usd='10',simulation_only=False,authorization=authorization)
    calls=[]
    async with LiveGenerator(output=tmp_path/'artifacts',ledger=ledger,rates={},authorization=authorization,
            credential_loader=lambda p:calls.append(p),wire_transport=httpx.MockTransport(lambda r:None)) as generator:
        with pytest.raises(DispatchPaused,match='rates'):
            await generator.generate(slot('OpenAI'),allowance_usd='.01')
        p.write_text(p.read_text()+' ')
        with pytest.raises(DispatchPaused,match='changed'):
            await generator.generate(slot('OpenAI'),allowance_usd='.01')
    assert calls==[] and ledger.snapshot()['attempts']==[]


def test_simulation_and_live_ledgers_cannot_be_reused_or_raise_the_limit(tmp_path):
    p=tmp_path/'spend.sqlite';SpendingLedger(p,limit_usd='10')
    authorization=ExecutionPermit(permit_file(tmp_path))
    with pytest.raises(ValueError,match='simulation ledger'):
        SpendingLedger(p,limit_usd='10',simulation_only=False,authorization=authorization)
    with pytest.raises(DispatchPaused,match='limit'):
        SpendingLedger(tmp_path/'other.sqlite',limit_usd='20',simulation_only=False,authorization=authorization)


class ProcessStopped(BaseException):
    pass


class CrashStream(httpx.AsyncByteStream):
    def __init__(self,wire):self.wire=wire
    async def __aiter__(self):
        yield self.wire
        raise ProcessStopped('simulated process death')


@pytest.mark.parametrize('provider',list(ENDPOINTS))
async def test_crash_after_terminal_response_recovers_exact_source_without_another_call(tmp_path,provider):
    calls=[]
    def handler(request):
        calls.append(1)
        raw=fixture(provider,json.loads(request.content)['model'])
        return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=CrashStream(sse_bytes(stream_events(provider,raw))),request=request)
    generator=offline(tmp_path,handler);s=slot(provider)
    with pytest.raises(ProcessStopped):await generator.generate(s,allowance_usd='.01')
    artifact=tmp_path/'artifacts'/s['artifact_id']
    assert not (artifact/'metadata.json').exists()
    assert generator.ledger.snapshot()['attempts'][0]['state']=='inflight'
    recovery_ledger=SpendingLedger.open_for_recovery(tmp_path/'spend.sqlite')
    recovered=recover_saved_response(artifact,ledger=recovery_ledger)
    assert recovered['output_retained'] and recovered['metadata']['generation_status']=='completed'
    assert (artifact/'app.py').read_text()==SOURCE and recovered['model_api_calls']==0
    assert recovery_ledger.snapshot()['held']==0
    again=recover_saved_response(artifact,ledger=recovery_ledger)
    assert again['metadata']==recovered['metadata'] and len(calls)==1
    with pytest.raises(DispatchPaused,match='recovery-only'):
        recovery_ledger.reserve('other','OpenAI','x','.01')


@pytest.mark.parametrize('with_answer',[False,True])
async def test_crashed_partial_stream_stays_unfilled_or_incomplete_never_regenerated(tmp_path,with_answer):
    events=stream_events('OpenAI',fixture('OpenAI'))[:2 if with_answer else 1]
    calls=[]
    def handler(request):
        calls.append(1)
        return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=CrashStream(sse_bytes(events)),request=request)
    generator=offline(tmp_path,handler);s=slot('OpenAI')
    with pytest.raises(ProcessStopped):await generator.generate(s,allowance_usd='.01')
    artifact=tmp_path/'artifacts'/s['artifact_id']
    report=recover_saved_response(artifact,ledger=SpendingLedger.open_for_recovery(tmp_path/'spend.sqlite'))
    assert report['output_retained']==with_answer
    if with_answer:assert report['metadata']['generation_status']=='incomplete' and (artifact/'app.py').read_text()==SOURCE
    else:assert not (artifact/'metadata.json').exists()
    assert generator.ledger.snapshot()['held']==10000000 and len(calls)==1


async def test_recovery_refuses_live_slot_and_changed_source_evidence(tmp_path):
    started,release=asyncio.Event(),asyncio.Event()
    async def handler(request):
        started.set();await release.wait()
        return httpx.Response(200,json=fixture('OpenAI'),request=request)
    generator=offline(tmp_path,handler);s=slot('OpenAI')
    job=asyncio.create_task(generator.generate(s,allowance_usd='.01'))
    await started.wait();artifact=tmp_path/'artifacts'/s['artifact_id']
    try:
        with pytest.raises(DispatchPaused,match='still active'):
            recover_saved_response(artifact,ledger=generator.ledger)
    finally:
        release.set()
        await job
    original=(artifact/'app.py').read_bytes()
    (artifact/'attempt_01/wire_response.bin').write_bytes(b'tampered')
    with pytest.raises(DispatchPaused,match='wire bytes'):
        recover_saved_response(artifact,ledger=generator.ledger)
    assert (artifact/'app.py').read_bytes()==original


async def test_recovery_rejects_different_existing_output_and_can_resume_publication(tmp_path,monkeypatch):
    generator=offline(tmp_path,lambda r:httpx.Response(200,json=fixture('OpenAI'),request=r));s=slot('OpenAI')
    from benchmark.expanded import provider_generation
    original=provider_generation.publish_output
    monkeypatch.setattr(provider_generation,'publish_output',lambda *a,**k: (_ for _ in ()).throw(ProcessStopped()))
    with pytest.raises(ProcessStopped):await generator.generate(s,allowance_usd='.01')
    monkeypatch.setattr(provider_generation,'publish_output',original)
    artifact=tmp_path/'artifacts'/s['artifact_id'];(artifact/'app.py').write_text('different saved code\n')
    with pytest.raises(DispatchPaused,match='overwrite'):
        recover_saved_response(artifact,ledger=generator.ledger)
    assert not (artifact/'metadata.json').exists()


def test_reconciliation_needs_evidence_and_does_not_erase_overruns_or_unfinished_costs(tmp_path):
    ledger=SpendingLedger(tmp_path/'spend.sqlite',limit_usd='1')
    a=ledger.reserve('one','OpenAI','x','.1');ledger.finish(a['id'],cost_usd=None,outcome='incomplete',consume=True)
    ledger.pause('OpenAI','billing review')
    evidence=tmp_path/'billing.txt';evidence.write_text('SYNTHETIC verified invoice record, no real charges')
    with pytest.raises(DispatchPaused,match='uncertain'):
        ledger.clear_pause('OpenAI',evidence_path=evidence,reason='checked')
    with pytest.raises(ValueError,match='supporting evidence'):
        ledger.reconcile_cost(a['id'],cost_usd='0',evidence_path=tmp_path/'missing',reason='checked')
    ledger.reconcile_cost(a['id'],cost_usd='.2',evidence_path=evidence,reason='synthetic observed cost')
    assert ledger.snapshot()['cost']==200000000 and any(p['provider']=='*' for p in ledger.snapshot()['pauses'])
    ledger.clear_pause('OpenAI',evidence_path=evidence,reason='charges checked')
    with pytest.raises(DispatchPaused):ledger.reserve('two','Google','y','.1')
    ledger.reconcile_cost(a['id'],cost_usd='1.2',evidence_path=evidence,reason='synthetic invoice correction')
    with pytest.raises(DispatchPaused,match='limit'):
        ledger.clear_pause('*',evidence_path=evidence,reason='cannot approve overrun')


def test_mock_permission_can_never_open_a_real_network_transport(tmp_path):
    authorization=ExecutionPermit(permit_file(tmp_path))
    with pytest.raises(DispatchPaused,match='real network'):
        AuthenticatedTransport(permit=authorization)


async def test_crash_after_artifact_publication_recovers_ledger_without_replacing_output(tmp_path,monkeypatch):
    generator=offline(tmp_path,lambda r:httpx.Response(200,json=fixture('OpenAI'),request=r));s=slot('OpenAI')
    monkeypatch.setattr(generator.ledger,'finish',lambda *a,**k: (_ for _ in ()).throw(ProcessStopped()))
    with pytest.raises(ProcessStopped):await generator.generate(s,allowance_usd='.01')
    artifact=tmp_path/'artifacts'/s['artifact_id']
    before={p.name:p.read_bytes() for p in artifact.iterdir() if p.is_file()}
    report=recover_saved_response(artifact,ledger=SpendingLedger.open_for_recovery(tmp_path/'spend.sqlite'))
    assert report['output_retained']
    assert all((artifact/name).read_bytes()==content for name,content in before.items())
    assert generator.ledger.snapshot()['attempts'][0]['state']=='settled'


def test_recovery_only_open_does_not_need_valid_current_permission(tmp_path):
    p=permit_file(tmp_path);authorization=ExecutionPermit(p)
    ledger=SpendingLedger(tmp_path/'live.sqlite',limit_usd='10',simulation_only=False,authorization=authorization)
    attempt=ledger.reserve('slot','OpenAI','x','.01')
    ledger.finish(attempt['id'],cost_usd=None,outcome='service_unfilled')
    p.unlink()
    recovery=SpendingLedger.open_for_recovery(tmp_path/'live.sqlite')
    evidence=tmp_path/'billing.txt';evidence.write_text('SYNTHETIC confirmed zero charge')
    recovery.reconcile_cost(attempt['id'],cost_usd='0',evidence_path=evidence,reason='synthetic review')
    assert recovery.snapshot()['held']==0
    with pytest.raises(DispatchPaused,match='recovery-only'):
        recovery.reserve('another','OpenAI','y','.01')


@pytest.mark.parametrize('mode',['no_code','truncated','refused','syntax_error'])
async def test_recovery_preserves_unsuccessful_returned_outputs(tmp_path,monkeypatch,mode):
    raw=fixture('OpenAI')
    if mode=='no_code':raw['output']=[]
    elif mode=='truncated':raw.update(status='incomplete',incomplete_details={'reason':'max_output_tokens'})
    elif mode=='refused':raw['output']=[{'type':'message','content':[{'type':'refusal','refusal':'synthetic refusal'}]}]
    else:raw['output']=[{'type':'message','content':[{'type':'output_text','text':'def broken(\n'}]}]
    calls=[]
    def handler(request):
        calls.append(1)
        return httpx.Response(200,json=raw,request=request)
    generator=offline(tmp_path,handler);s=slot('OpenAI')
    from benchmark.expanded import provider_generation
    original=provider_generation.publish_output
    monkeypatch.setattr(provider_generation,'publish_output',lambda *a,**k: (_ for _ in ()).throw(ProcessStopped()))
    with pytest.raises(ProcessStopped):await generator.generate(s,allowance_usd='.01')
    monkeypatch.setattr(provider_generation,'publish_output',original)
    artifact=tmp_path/'artifacts'/s['artifact_id']
    report=recover_saved_response(artifact,ledger=SpendingLedger.open_for_recovery(tmp_path/'spend.sqlite'))
    assert report['output_retained'] and len(calls)==1
    assert report['metadata']['generation_status']==('completed' if mode=='syntax_error' else mode)
    if mode=='syntax_error':assert (artifact/'app.py').read_text()=='def broken(\n'
    if mode=='no_code':assert not (artifact/'app.py').exists()


def test_invalid_prices_are_rejected_before_dispatch(tmp_path):
    rates=dict(RATES);name=next(iter(rates));rates[name]=TokenRates('-1','10','synthetic://invalid','2026-10-20')
    authorization=ExecutionPermit(permit_file(tmp_path,token_rates={n:asdict(r) for n,r in rates.items()}))
    with pytest.raises(DispatchPaused,match='invalid reviewed token prices'):
        authorization.validate_slot(slot('OpenAI'),rates)
