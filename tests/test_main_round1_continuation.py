"""Continuation scope, preservation, budget and credential-isolation controls."""
import asyncio,json,re,sqlite3,sys
from pathlib import Path
from decimal import Decimal
from types import SimpleNamespace
import pytest
from benchmark.expanded.planning import allocation
from benchmark.expanded.spending import DispatchPaused,SpendingLedger
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import continue_main_round1 as d

def test_complete_round_has_exactly720_unique_balanced_outputs_and_no_later_round():
    p,old=d.plan();seen=set();totals=[]
    for provider in d.PROVIDERS:
        initial=old['slots'][provider];ids=[s['artifact_id'] for s in initial]
        for wave in range(6):
            selected=d.slots(provider,wave)
            assert len(selected)<=60 and len(selected)%10==0
            assert all(s['cohort']=='main' and s['round']==1 and s['provider']==provider for s in selected)
            assert sum(s['condition']=='C0' for s in selected)==len(selected)//2
            ids.extend(s['artifact_id'] for s in selected)
        expected=[s['artifact_id'] for s in allocation()[0] if s['provider']==provider and s['round']==1]
        assert ids==expected and not seen.intersection(ids);seen.update(ids)
    assert len(seen)==720
    assert [sum(len(d.slots(v,w)) for v in d.PROVIDERS) for w in range(6)]==[240,140,120,110,60,10]

@pytest.mark.parametrize('wave',[-1,6,True,None])
def test_round_two_or_invalid_wave_is_rejected(wave):
    with pytest.raises(DispatchPaused):d.slots('OpenAI',wave)

def make_ledger(tmp_path,unsettled=False):
    db=tmp_path/'spending.sqlite';ledger=SpendingLedger(db,limit_usd='2')
    attempt=ledger.reserve('old-slot','Mistral','unchanged-fingerprint','.1')
    if not unsettled:ledger.finish(attempt['id'],outcome='output',cost_usd='.03',consume=True)
    old=tmp_path/'original_permission.json';old.write_text('original permission')
    new=tmp_path/'new_permission.json';new.write_text('scoped continuation permission')
    conn=sqlite3.connect(db)
    with conn:
        conn.execute("update settings set value='false' where name='simulation_only'")
        conn.execute("insert into settings values ('execution_permit',?)",(d.sha(old),))
    conn.close();return db,old,new

def test_reviewed_copy_preserves_charges_attempts_slots_and_original_ledger(tmp_path):
    db,old,new=make_ledger(tmp_path);original=db.read_bytes();before=d.ledger_rows(db)
    copy=tmp_path/'copy.sqlite';copy.write_bytes(original)
    recorded=d.amend_copy_permission(copy,old,new,'2','prior-archive-sha')
    after=d.ledger_rows(copy)
    assert recorded==before and db.read_bytes()==original
    for table in ['attempts','slots','pauses']:assert after[table]==before[table]
    assert {r['name']:r['value'] for r in after['settings']}['limit']=='2000000000'
    assert sum(r['charged'] for r in after['attempts'])==30000000
    assert after['audit'][:-1]==before['audit'] and after['audit'][-1]['event']=='explicit_scoped_continuation'

def test_uncertain_charge_cannot_be_cleared_by_continuation(tmp_path):
    db,old,new=make_ledger(tmp_path,unsettled=True);before=db.read_bytes()
    with pytest.raises(DispatchPaused):d.amend_copy_permission(db,old,new,'2','sha')
    assert db.read_bytes()==before

@pytest.mark.parametrize('maximum',['1','20'])
def test_cap_change_cannot_hide_in_permission_amendment(tmp_path,maximum):
    db,old,new=make_ledger(tmp_path);before=db.read_bytes()
    with pytest.raises(DispatchPaused):d.amend_copy_permission(db,old,new,maximum,'sha')
    assert db.read_bytes()==before

async def test_fixed_pair_loop_accepts_model_failures_without_replacement(tmp_path,monkeypatch):
    chosen=d.slots('Mistral',0);active=0;peak=0;called=[];campaign=tmp_path/'campaign';campaign.mkdir()
    class FakeGenerator:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def authorize_slot(self,s):pass
        async def generate(self,s,**kwargs):
            nonlocal active,peak
            self.authorize_slot(s);active+=1;peak=max(peak,active);called.append(s)
            await asyncio.sleep(0);active-=1
            return {'generation_status':'syntax_error','artifact_id':s['artifact_id']}
    old=d.original_plan();m={'slots':chosen,'run_id':1}
    monkeypatch.setattr(d,'LiveGenerator',FakeGenerator)
    monkeypatch.setattr(d,'context',lambda *a:({},old,m,campaign,tmp_path,None,None))
    monkeypatch.setattr(d,'summarize',lambda *a:{'retained':len(called)})
    report=await d.generate('Mistral',0,tmp_path)
    assert report['retained']==60 and called==chosen and peak==2
    with pytest.raises(DispatchPaused):await d.generate('Mistral',0,tmp_path)
    assert len(called)==60

def test_paid_preparation_needs_live_workflow_identity_before_fetch(tmp_path,monkeypatch):
    monkeypatch.delenv('GITHUB_REPOSITORY',raising=False)
    monkeypatch.setattr(d,'fetch_named',lambda *a:pytest.fail('no network before workflow check'))
    with pytest.raises(DispatchPaused):d.prepare('OpenAI',0,tmp_path/'absent')

def test_workflow_waits_for_every_prior_audit_and_isolates_all_model_secrets():
    text=(ROOT/'.github/workflows/expanded-local-validation.yml').read_text()
    assert '  actions: read' in text and 'persist-credentials: false' in text
    pieces=re.split(r'^  ([a-z][a-z0-9-]+):\n',text.split('jobs:\n',1)[1],flags=re.M)
    jobs=dict(zip(pieces[1::2],pieces[2::2]));assert len(jobs)==20
    for wave in range(6):
        generation=jobs[f'round1-w{wave}-generation']
        assert ('round1-software-gate' in generation.split('    steps:')[0])
        if wave:assert f'round1-w{wave-1}-audit' in generation.split('    steps:')[0]
        assert generation.count('ROUND1_PROVIDER_API_KEY: ${{ secrets[matrix.secret_name] }}')==1
        assert generation.index('prepare --provider')<generation.index('ROUND1_PROVIDER_API_KEY')
        for kind in ['evaluation','audit']:
            body=jobs[f'round1-w{wave}-{kind}']
            assert 'secrets[' not in body and 'ROUND1_PROVIDER_API_KEY' not in body
        assert f'needs: round1-w{wave}-generation' in jobs[f'round1-w{wave}-evaluation']
        assert f'needs: round1-w{wave}-evaluation' in jobs[f'round1-w{wave}-audit']
    assert 'round1-w6' not in text and 'verified_software_run' in text
    assert '!inputs.round1_continuation' in jobs['local-validation']
