"""Budget continuation must preserve costs, original bytes and completed output."""
import importlib.util,json,sqlite3,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('xai_budget_continuation',ROOT/'scripts/resume_xai_budget_validation.py')
wrapper=importlib.util.module_from_spec(spec);spec.loader.exec_module(wrapper)

def original_ledger(path,cost=526958000):
    db=sqlite3.connect(path)
    db.executescript('''CREATE TABLE settings(name TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE slots(id TEXT PRIMARY KEY,fingerprint TEXT,provider TEXT,consumed INTEGER);
    CREATE TABLE attempts(id TEXT PRIMARY KEY,slot_id TEXT,number INTEGER,provider TEXT,state TEXT,reserved INTEGER,charged INTEGER,outcome TEXT,response_id TEXT);
    CREATE TABLE pauses(provider TEXT PRIMARY KEY,reason TEXT NOT NULL);
    CREATE TABLE audit(sequence INTEGER PRIMARY KEY,utc TEXT NOT NULL,event TEXT NOT NULL,details TEXT NOT NULL);''')
    db.executemany('INSERT INTO settings VALUES (?,?)',[('limit','8000000000'),('simulation_only','false'),('execution_permit','old-permit')])
    db.execute('INSERT INTO slots VALUES (?,?,?,?)',(wrapper.FIRST,'same-settings','xAI',1))
    db.execute('INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?,?)',(wrapper.FIRST+':1',wrapper.FIRST,1,'xAI','settled',500000000,cost,'completed','saved-response'))
    db.execute('INSERT INTO pauses VALUES (?,?)',('*','observed cost exceeded allowance or overall limit; review required'))
    db.commit();db.close()


def test_budget_migration_preserves_original_cost_attempt_consumption_and_original_bytes(tmp_path):
    original=tmp_path/'original.sqlite';original_ledger(original);before=original.read_bytes()
    review=tmp_path/'review.json';review.write_text('{"author_approved":true}')
    dest=tmp_path/'copy.sqlite';snapshot=wrapper.migrate_ledger(original,dest,SimpleNamespace(fingerprint='new-permit'),review)
    assert original.read_bytes()==before and snapshot['cost']==526958000 and snapshot['held']==0
    assert len(snapshot['attempts'])==1 and snapshot['attempts'][0]['slot_id']==wrapper.FIRST
    assert snapshot['limit_units']==12000000000 and not snapshot['pauses']
    db=sqlite3.connect(dest)
    assert db.execute('SELECT consumed FROM slots').fetchall()==[(1,)]
    assert db.execute('SELECT event FROM audit ORDER BY sequence').fetchall()==[('reviewed_budget_continuation',),('clear_pause',)]
    details=json.loads(db.execute("SELECT details FROM audit WHERE event='reviewed_budget_continuation'").fetchone()[0])
    assert details['retained_cost_usd']=='0.526958' and details['previous_limit_usd']=='8' and details['new_limit_usd']=='12'
    db.close()


def test_existing_copy_is_never_overwritten(tmp_path):
    original=tmp_path/'original.sqlite';original_ledger(original);dest=tmp_path/'copy.sqlite';dest.write_bytes(b'preserved')
    with pytest.raises(wrapper.DispatchPaused,match='already exists'):wrapper.migrate_ledger(original,dest,None,None)
    assert dest.read_bytes()==b'preserved'


def test_wrong_carried_cost_blocks_amendment(tmp_path):
    original=tmp_path/'original.sqlite';original_ledger(original,cost=1);before=original.read_bytes()
    with pytest.raises(wrapper.DispatchPaused,match='accounting missing'):wrapper.migrate_ledger(original,tmp_path/'copy.sqlite',None,None)
    assert original.read_bytes()==before


def test_absent_author_budget_approval_blocks_before_preparation_or_credentials(tmp_path,monkeypatch):
    monkeypatch.setattr(wrapper,'load_plan',lambda:{'budget_amendment_author_approved':False})
    monkeypatch.setattr(wrapper,'workflow_identity',lambda:None)
    monkeypatch.setattr(wrapper,'environment_credential',lambda *a:pytest.fail('must not read a key'))
    with pytest.raises(wrapper.DispatchPaused,match='specific budget approval'):wrapper.prepare(tmp_path/'state',tmp_path/'absent.json')
    assert not (tmp_path/'state').exists()


def test_plan_excludes_the_retained_slot_and_keeps_original_model_settings():
    plan=wrapper.load_plan()
    assert type(plan['budget_amendment_author_approved']) is bool
    assert len(plan['slots'])==15 and wrapper.FIRST not in {s['artifact_id'] for s in plan['slots']}
    original=json.loads((ROOT/'scripts/expanded_xai_request_recovery_plan.json').read_text())
    assert plan['slots']==original['slots'][1:] and plan['retained_slot']==original['slots'][0]
    assert plan['snapshot']==original['snapshot'] and plan['token_rates']==original['token_rates']


def test_continuation_workflow_isolates_keys_and_cannot_select_completed_coordinate():
    text=(ROOT/'.github/workflows/full-study.yml').read_text()
    job=text.split('  grok-budget-continuation:',1)[1].split('  uniform-saved-source-evaluation:',1)[0]
    assert 'inputs.continue_grok_budget &&' in job and 'persist-credentials: false' in job
    assert 'github.run_attempt == \'1\'' in job
    keyed=[s for s in job.split('      - ') if 'secrets.GROK_API_KEY' in s]
    assert len(keyed)==16
    assert all(' resume_xai_budget_validation.py ' not in s for s in keyed)
    assert all('scripts/resume_xai_budget_validation.py access' in s or 'scripts/resume_xai_budget_validation.py group' in s for s in keyed)
    token=[s for s in job.split('      - ') if 'GH_TOKEN:' in s]
    assert len(token)==1 and ' prior-run-check ' in token[0] and ' group ' not in token[0]
    assert job.index('Preserve stable continuation marker')<job.index('Verify model metadata')
    assert [int(s.split('--index ',1)[1].splitlines()[0]) for s in job.split('      - ') if '--index ' in s]==list(range(15))


def test_all_other_jobs_exclude_budget_continuation():
    text=(ROOT/'.github/workflows/full-study.yml').read_text()
    before,after=text.split('  grok-budget-continuation:',1)
    after=after.split('  uniform-saved-source-evaluation:',1)[1]
    guards=[line for line in (before+after).splitlines() if line.startswith('    if:')]
    assert len(guards)==9 and all('!inputs.continue_grok_budget' in line for line in guards)
