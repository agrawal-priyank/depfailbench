"""Two bounded exceptions, no repeated calls or remeasurement of completed wave0."""
import json,sqlite3
from collections import Counter
import pytest
import continue_main_remaining as gen
import evaluate_main_remaining as ev
import control_main_remaining as control
from benchmark.expanded.spending import DispatchPaused


def test_exact_unmade_scope_and_retained_saved_wave(monkeypatch):
    p,_=gen.plan();new=[];measure=[]
    for r in range(4,7):
        monkeypatch.setenv('REMAINING_ROUND',str(r))
        for w in range(6):
            for provider in gen.PROVIDERS:
                group=gen.generation_slots(provider,w);assert len(group)<=60;new+=group
                if (r,w)!=(4,0):measure+=gen.slots(provider,w)
    ids={s['artifact_id'] for s in new}
    assert len(new)==len(ids)==1760 and len(measure)==1920
    assert not ids & set(p['all_retained_artifact_ids']) and len(p['all_retained_artifact_ids'])==2560
    assert sum(len(v['retained_ids']) for v in p['partial_sources'].values())==160
    monkeypatch.setenv('REMAINING_ROUND','4')
    assert all(not gen.generation_slots(v,w) for v in gen.PROVIDERS for w in [0,1])
    assert Counter(s['provider'] for s in new)=={'Anthropic':160,'OpenAI':840,'Google':160,'Mistral':600}


@pytest.mark.parametrize('damage',['second_uncertain','wrong_id','wrong_reserved','wrong_response','extra_pause','wrong_provider'])
def test_google_allowance_rejects_any_other_issue(tmp_path,damage):
    e=gen.load(gen.PLAN)['approved_google_exception'];f=tmp_path/'copy.sqlite';db=sqlite3.connect(f)
    db.executescript('''create table settings(name text,value text);create table attempts(id text,state text,charged integer,reserved integer,response_id text,provider text,outcome text);create table slots(id text);create table pauses(provider text,reason text);create table audit(id integer,event text,details text);''')
    db.execute('insert into attempts values(?,?,?,?,?,?,?)',(e['attempt_id'],'uncertain',None,150000000,None,'Google','service_unfilled'))
    if damage=='second_uncertain':db.execute("insert into attempts values('other','uncertain',null,150000000,null,'Google','service_unfilled')")
    if damage=='wrong_id':db.execute("update attempts set id='other'")
    if damage=='wrong_reserved':db.execute('update attempts set reserved=140000000')
    if damage=='wrong_response':db.execute("update attempts set response_id='other'")
    if damage=='wrong_provider':db.execute("update attempts set provider='OpenAI'")
    if damage=='extra_pause':db.execute("insert into pauses values('*','other')")
    db.commit();db.close();before=gen.sha(f)
    with pytest.raises(DispatchPaused):gen.apply_single_allowance_copy(f,tmp_path/'evidence.json')
    assert gen.sha(f)==before


def test_original_openai_exception_stays_hash_bound():
    p,_=gen.plan();e=p['approved_usage_exception'];g=p['approved_google_exception']
    assert e['wire_sha256']=='18da56c9da1ebd01d3cc7e2d7eaf96347cdd658de3f11b95e71e6f966926fed3' and e['amount_usd']=='0.025'
    assert g['wire_sha256']=='b61e0a5698d9d416df8ff5537d7aae7cd8ccedafe7430f4b63eaa18d3da17109' and g['operational_allowance_usd']=='0.15'
    assert e['authorization_sha256']!=g['authorization_sha256']


def test_only_exact_google_attempt_can_use_second_exception():
    assert ev.verify_google503_allowance(None,None,None,None,{'id':'another'},None,None) is False


def test_initial_entry_uses_terminal_exact_gate_and_preserved_round3(tmp_path,monkeypatch):
    p,_=gen.plan();run=999;software=111;commit='controlled-no-dispatch'
    monkeypatch.setattr(control,'identity',lambda:None);monkeypatch.setenv('REMAINING_ROUND','4');monkeypatch.setenv('REMAINING_MODE','paid');monkeypatch.setenv('VERIFIED_SOFTWARE_RUN',str(software));monkeypatch.setenv('GITHUB_SHA',commit);monkeypatch.setenv('GITHUB_RUN_ID',str(run));monkeypatch.setenv('PREVIOUS_ROUND_RUN','39929309804')
    def get(path):
        ident=int(path.split('/')[-1]);old=ident!=software
        return {'status':'completed','conclusion':'failure' if ident in [39891567130,39929309804] else 'success','run_attempt':1,'head_sha':p['upload_recovery']['commit'] if ident==39929309804 else p['original_round3']['commit'] if old else commit,'head_branch':p['upload_recovery']['branch'] if ident==39929309804 else p['branch'],'workflow_id':p['workflow_id']}
    def fetch(run,sha,name,out):
        (out/'contents').mkdir(parents=True)
        if run==software:
            data={'passed':True,'tests':p['expected_software_tests'],'commit':commit,'run_id':software,'attempt':1,'mode':'software','plan_sha256':gen.sha(gen.PLAN),'model_api_calls':0};target=out/'contents/software_gate.json'
        else:data={'passed':True,'round':3,'new_outputs':720,'records':6480,'groups':14};target=out/'contents/round_completion.json'
        target.write_text(json.dumps(data))
    monkeypatch.setattr(control,'get',get);monkeypatch.setattr(control,'fetch_named',fetch);control.entry(tmp_path/'entry')
    assert gen.load(tmp_path/'entry/entry.json')['passed']


def test_initial_wave_skip_does_not_suppress_following_jobs():
    text=(gen.ROOT/'.github/workflows/expanded-local-validation.yml').read_text()
    assert "if: ${{ inputs.round_id != '4' }}" in text
    assert "needs: [entry, w0-audit]" in text
    assert "always() && needs.entry.result == 'success' && (inputs.round_id == '4' || needs.w1-generation.result == 'success')" in text
    for w in range(6):
        assert (f"always() && needs.w{w}-generation.result == 'success'" in text) if w!=1 else "inputs.round_id == '4' || needs.w1-generation.result == 'success'" in text
        assert f"always() && needs.w{w}-evaluation.result == 'success'" in text
    assert "inputs.round_id == '4' || needs.w0-audit.result == 'success'" in text.split('  completion:',1)[1]


@pytest.mark.parametrize('provider',gen.PROVIDERS)
def test_upload_recovery_pins_all_original_generation(provider,monkeypatch):
    monkeypatch.setenv('REMAINING_ROUND','4')
    s=gen.saved_origin('generation',provider,1)
    assert (s['run_id'],s['commit'])==(39929309804,'5cc5a1ba1104d26bda10ef133a55fb472e9c133e')
    assert not gen.generation_slots(provider,1)


@pytest.mark.parametrize('r',[4,5,6])
def test_upload_recovery_reuses_only_fifteen_original_shards(r,monkeypatch):
    monkeypatch.setenv('REMAINING_ROUND',str(r))
    reused=[(v,s) for v in gen.PROVIDERS for s in range(4) if gen.saved_origin('evaluation',v,1,s)]
    assert len(reused)==(15 if r==4 else 0)
    assert ('Anthropic',2) not in reused


def test_upload_recovery_refuses_remeasurement_of_saved_shard(monkeypatch,tmp_path):
    p,_=gen.plan();monkeypatch.setenv('REMAINING_ROUND','4')
    monkeypatch.setattr(ev,'identity',lambda:None);monkeypatch.setenv('GITHUB_RUN_ID','999');monkeypatch.setenv('GITHUB_SHA','fixture')
    monkeypatch.setattr(ev,'fetch_named',lambda *a:pytest.fail('must stop before fetch or execution'))
    with pytest.raises(DispatchPaused):ev.prepare('OpenAI',1,0,tmp_path/'output')


@pytest.mark.parametrize('damage',['id','name','digest'])
def test_upload_recovery_rejects_wrong_saved_archive(damage,monkeypatch,tmp_path):
    monkeypatch.setenv('REMAINING_ROUND','4');s=gen.saved_origin('generation','OpenAI',1)
    (tmp_path/'archive.zip').write_bytes(b'fixture')
    m={'id':s['artifact_id'],'name':s['artifact_name']}
    if damage=='id':m['id']+=1
    if damage=='name':m['name']+='wrong'
    (tmp_path/'metadata.json').write_text(json.dumps(m))
    with pytest.raises(DispatchPaused):gen.verify_saved_origin(tmp_path,'generation','OpenAI',1)


def test_upload_recovery_only_missing_shard_is_scheduled():
    text=(gen.ROOT/'.github/workflows/expanded-local-validation.yml').read_text()
    block=text.split('  w1-evaluation:',1)[1].split('  w1-audit:',1)[0]
    assert "fromJSON(" in block and '"provider": "Anthropic", "slug": "anthropic", "shard": 2' in block
    assert 'needs: [entry, w1-generation]' in block
    assert 'secrets' not in block


@pytest.mark.parametrize('provider',['Anthropic','Google'])
def test_round5_source_lookup_preserves_saved_round4_origin(provider,monkeypatch):
    monkeypatch.setenv('REMAINING_ROUND','5')
    assert gen.saved_origin('generation',provider,1) is None
    run,commit=gen.origin_identity('generation',provider,1,999,'current',round_id=4)
    assert run==39929309804 and commit=='5cc5a1ba1104d26bda10ef133a55fb472e9c133e'
