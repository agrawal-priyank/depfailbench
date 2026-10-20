"""Grok compatibility, scoped replay, accounting and total retry bounds."""
import importlib.util,json,sys
from pathlib import Path
import pytest
from benchmark.expanded.planning import allocation
from benchmark.expanded.spending import DispatchPaused
ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('xai_request_recovery_test',ROOT/'scripts/expanded_xai_request_recovery.py')
batch=importlib.util.module_from_spec(spec);spec.loader.exec_module(batch)

def test_wrong_previous_archive_stops_before_reconciliation():
    batch.select_provider('xAI')
    with pytest.raises(DispatchPaused,match='archive differs'):batch.verify_previous(b'wrong',batch.load_plan())

def test_only_original_xai_slots_allowed():
    batch.select_provider('xAI');p=batch.load_plan()
    assert len(p['slots'])==16 and all(s['provider']=='xAI' and s['cohort']=='validation' for s in p['slots'])
    assert p['batch_id']=='xai-request-recovery-20261020-v2' and p['maximum_cost_usd']=='8'
    with pytest.raises(DispatchPaused):batch.select_provider('OpenAI')

async def test_complete_mock_retains_exact_sixteen_and_duplicate_guard(tmp_path):
    batch.select_provider('xAI');r=await batch.mock_rehearsal(tmp_path/'mock')
    assert r['complete'] and r['mock_wire_calls']==16 and r['duplicate_dispatch_blocked'] and r['credential_canary_absent']

def test_previous_rejected_attempt_counts_toward_three_attempt_bound(tmp_path):
    batch.select_provider('xAI');batch.prepare(tmp_path/'mock',maximum_cost_usd='8')
    _,_,_,ledger=batch.context(tmp_path/'mock')
    for _ in range(2):
        a=ledger.reserve(batch.PRIOR_SLOT,'xAI','synthetic-fingerprint','.5')
        ledger.finish(a['id'],cost_usd='0',outcome='service_unfilled')
    with pytest.raises(DispatchPaused,match='three total attempts'):ledger.reserve(batch.PRIOR_SLOT,'xAI','synthetic-fingerprint','.5')
    assert len(ledger.snapshot()['attempts'])==2

def test_new_workflow_selects_only_grok_with_step_scoped_key():
    text=(ROOT/'.github/workflows/full-study.yml').read_text();job=text.split('  grok-request-recovery:',1)[1]
    assert 'resume_grok_request_fix' in job and 'github.run_attempt == \'1\'' in job
    assert 'expanded_xai_request_recovery.py' in job and 'xai-request-recovery-20261020-v2-prepared' in job
    assert 'secrets.OPENAI_API_KEY' not in job and 'secrets.ANTHROPIC_API_KEY' not in job
    assert 'XAI_API_KEY: ${{ secrets.GROK_API_KEY }}' in job
    prior=job.split('      - name: Check the stable prior-batch marker before preparation',1)[1].split('      - name: Prepare exact',1)[0]
    assert 'GH_TOKEN:' in prior and 'API_KEY:' not in prior
