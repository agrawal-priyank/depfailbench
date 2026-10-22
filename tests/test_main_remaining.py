"""Bounded paid scope, unchanged prior charges and credential-free partitions."""
import json,sqlite3,sys
from collections import Counter
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import continue_main_remaining as gen
import evaluate_main_remaining as ev
import control_main_remaining as control
from benchmark.expanded.spending import DispatchPaused


def test_exact_remaining_scope_and_cell_balance():
    p,old=gen.plan();all_slots=[]
    for r in range(2,7):
        group=[]
        for w in range(6):
            for provider in gen.PROVIDERS:
                chosen=gen.slots(provider,w,round_id=r)
                assert len(chosen)<=60
                assert all(s['round']==r for s in chosen)
                group+=chosen
        assert len(group)==720 and len({s['artifact_id'] for s in group})==720
        assert set(Counter((s['task'],s['configuration_id'],s['condition']) for s in group).values())=={5}
        all_slots+=group
    assert len(all_slots)==len({s['artifact_id'] for s in all_slots})==3600
    assert set(Counter((s['task'],s['configuration_id'],s['condition']) for s in all_slots).values())=={25}
    assert old['new_campaign_caps_usd']==p['new_campaign_caps_usd']


@pytest.mark.parametrize('round_id',[1,7,True,'2',None])
def test_outside_authorized_round_rejected(round_id,monkeypatch):
    if round_id is None:monkeypatch.setenv('REMAINING_ROUND','7')
    with pytest.raises(DispatchPaused):gen.slots('OpenAI',0,round_id=round_id)


@pytest.mark.parametrize('r',range(2,7))
def test_partition_keeps_all_nine_measurements_on_same_machine(r,monkeypatch):
    monkeypatch.setenv('REMAINING_ROUND',str(r))
    for provider in gen.PROVIDERS:
        for w in range(gen.last_wave(provider)+1):
            ids=[]
            for shard in range(4):ids.extend(s['artifact_id'] for s in ev.selected(provider,w,shard))
            assert len(ids)==len(set(ids))==len(gen.slots(provider,w))
            assert set(ids)=={s['artifact_id'] for s in gen.slots(provider,w)}
            before=[s for s in gen.prefix(provider,w) if s not in gen.slots(provider,w)]
            assert len(before)==(r-1)*{'Anthropic':80,'OpenAI':320,'Google':80,'Mistral':240}[provider]+60*w


@pytest.mark.parametrize('field,value',[('maximum_new_outputs',4320),('stop_at_cumulative_main',5040),('overall_envelope_usd','46'),('maximum_inflight_per_provider',3),('maximum_new_outputs_per_provider_batch',61),('evaluation_shards',8),('author_approved',False)])
def test_execution_bounds_fail_closed(field,value,tmp_path,monkeypatch):
    p=gen.load(gen.PLAN);p[field]=value;changed=tmp_path/'plan.json';changed.write_text(json.dumps(p));monkeypatch.setattr(gen,'PLAN',changed)
    with pytest.raises(DispatchPaused):gen.plan()


@pytest.mark.parametrize('credential',['GH_TOKEN','GITHUB_TOKEN','REMAINING_PROVIDER_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY','GEMINI_API_KEY','MISTRAL_API_KEY'])
def test_no_credential_reaches_program_execution(credential,tmp_path,monkeypatch):
    monkeypatch.setenv(credential,'controlled-test-placeholder')
    monkeypatch.setattr(ev,'collect',lambda *a,**k:pytest.fail('must stop before execution'))
    with pytest.raises(DispatchPaused):ev.evaluate('OpenAI',0,0,tmp_path)


def test_no_advance_beyond4320(tmp_path,monkeypatch):
    monkeypatch.setattr(control,'identity',lambda:None);monkeypatch.setenv('REMAINING_ROUND','6')
    monkeypatch.setattr(control,'get',lambda *a,**k:pytest.fail('must not dispatch'))
    with pytest.raises(DispatchPaused):control.advance(tmp_path)


def test_permission_copy_preserves_all_financial_evidence(tmp_path):
    old=tmp_path/'old.json';old.write_text('{"original":true}');new=tmp_path/'new.json';new.write_text('{"scope":"next60"}')
    dbpath=tmp_path/'ledger.sqlite';db=sqlite3.connect(dbpath)
    db.executescript('''create table settings(name text primary key,value text);create table attempts(id text,state text,charged integer);create table slots(id text);create table pauses(id text);create table audit(id integer primary key,utc text,event text,details text);''')
    db.executemany('insert into settings values(?,?)',[('limit','2000000000'),('simulation_only','false'),('execution_permit',gen.sha(old))])
    db.execute("insert into attempts values('original','settled',1000000)");db.execute("insert into slots values('original')");db.commit();db.close()
    before=gen.ledger_rows(dbpath)
    gen.amend_copy_permission(dbpath,old,new,'2','test-archive-digest')
    after=gen.ledger_rows(dbpath)
    assert all(before[k]==after[k] for k in ['attempts','slots','pauses'])
    assert len(after['audit'])==1
    db=sqlite3.connect(dbpath);db.execute("update attempts set state='uncertain'");db.commit();db.close()
    with pytest.raises(DispatchPaused):gen.amend_copy_permission(dbpath,new,old,'2','test')


def test_workflow_credential_isolation_and_wave_dependencies():
    text=(ROOT/'.github/workflows/expanded-local-validation.yml').read_text()
    assert 'cancel-in-progress: false' in text and "github.run_attempt == '1'" in text
    assert 'actions: write' in text and text.count('secrets[')==6
    assert "options: ['2', '3', '4', '5', '6']" in text and 'max-parallel: 16' in text
    for w in range(6):
        block=text.split(f'  w{w}-evaluation:',1)[1].split(f'  w{w}-audit:',1)[0]
        assert 'secrets' not in block
        measure=block.split('- name: Measure saved sources without credentials, one measurement at a time',1)[1].split('- uses:',1)[0]
        assert 'TOKEN' not in measure and 'prepare' not in measure
        assert f'needs: w{w}-generation' in block
        if w:assert f'needs: w{w-1}-audit' in text.split(f'  w{w}-generation:',1)[1].split('runs-on:',1)[0]
    assert text.index('Preserve advance intent before dispatch')<text.index('Start next exact-commit round once')
    assert "inputs.round_id != '6'" in text
