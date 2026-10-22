"""Scoped recovery uses retained outcomes, never retries unknown accepted requests."""
from pathlib import Path
import json,sqlite3
import pytest
import continue_main_remaining as gen
import evaluate_main_remaining as ev
from benchmark.expanded.spending import DispatchPaused


def test_exact_new_coordinate_set(monkeypatch):
    p,_=gen.plan();allnew=[];alleval=[]
    for r in range(3,7):
        monkeypatch.setenv('REMAINING_ROUND',str(r))
        for w in range(6):
            for provider in gen.PROVIDERS:
                chosen=gen.generation_slots(provider,w);allnew+=chosen;alleval+=gen.slots(provider,w)
                assert len(chosen)<=60
    assert len(allnew)==len({s['artifact_id'] for s in allnew})==2674
    assert len(alleval)==2880
    retained={i for v in p['partial_sources'].values() for i in v['retained_ids']}
    assert not retained & {s['artifact_id'] for s in allnew}
    assert p['approved_usage_exception']['artifact_id'] in retained
    monkeypatch.setenv('REMAINING_ROUND','3')
    assert {v:len(gen.generation_slots(v,0)) for v in gen.PROVIDERS}=={'Anthropic':0,'OpenAI':34,'Google':0,'Mistral':0}


@pytest.mark.parametrize('damage',['second_uncertain','wrong_id','wrong_reserved','wrong_response','extra_pause'])
def test_allowance_does_not_clear_other_financial_issues(tmp_path,damage):
    e=gen.load(gen.PLAN)['approved_usage_exception'];dbpath=tmp_path/'copy.sqlite';db=sqlite3.connect(dbpath)
    db.executescript('''create table settings(name text,value text);create table attempts(id text,state text,charged integer,reserved integer,response_id text);create table slots(id text);create table pauses(provider text,reason text);create table audit(id integer,event text,details text);''')
    db.execute('insert into attempts values(?,?,?,?,?)',(e['attempt_id'],'uncertain',None,25000000,e['response_id']))
    db.execute("insert into pauses values('OpenAI','output retained but billing usage requires reconciliation')")
    if damage=='second_uncertain':db.execute("insert into attempts values('other','uncertain',null,25000000,'other')")
    if damage=='wrong_id':db.execute("update attempts set id='other'")
    if damage=='wrong_reserved':db.execute('update attempts set reserved=24000000')
    if damage=='wrong_response':db.execute("update attempts set response_id='other'")
    if damage=='extra_pause':db.execute("insert into pauses values('*','other')")
    db.commit();db.close();before=gen.sha(dbpath)
    with pytest.raises(DispatchPaused):gen.apply_single_allowance_copy(dbpath,tmp_path/'evidence.json')
    assert gen.sha(dbpath)==before


def test_unknown_other_response_never_gets_exception():
    assert ev.verify_single_unknown_usage(None,None,'OpenAI',{'artifact_id':'another'},None,None,None,None) is False


def test_old_source_hashes_and_authorization_bound():
    p,_=gen.plan();e=p['approved_usage_exception']
    assert e['wire_sha256']=='18da56c9da1ebd01d3cc7e2d7eaf96347cdd658de3f11b95e71e6f966926fed3'
    assert e['amount_usd']=='0.025' and e['authorization_sha256']==p['approved_recovery_authorization_sha256']
    assert sum(len(v['retained_ids']) for v in p['partial_sources'].values())==206
