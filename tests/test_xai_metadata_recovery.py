"""Zero-request recovery must fail closed on any evidence of prior generation."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import zipfile

import pytest
from benchmark.expanded.spending import DispatchPaused

spec = importlib.util.spec_from_file_location('xai_recovery_test', Path(__file__).parents[1] / 'scripts/recover_xai_metadata_failure.py')
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


@pytest.fixture(autouse=True)
def historical_recovery_mock_plan(tmp_path,monkeypatch):
    # Actual old recovery remains bound to its old core and cannot run again.
    original_select=recovery.batch.select_provider
    def select(provider):
        original_select(provider)
        plan=json.loads(recovery.batch.PLAN_PATH.read_text());plan['snapshot']=recovery.batch.execution_snapshot()
        path=tmp_path/'historical_recovery_mock_plan.json';path.write_text(json.dumps(plan))
        monkeypatch.setattr(recovery.batch,'PLAN_PATH',path)
    monkeypatch.setattr(recovery.batch,'select_provider',select)


@pytest.fixture
def previous(tmp_path, monkeypatch):
    recovery.batch.select_provider('xAI')
    plan = recovery.batch.load_plan()
    dbpath = tmp_path / 'ledger.sqlite'
    db = sqlite3.connect(dbpath)
    for table in ('slots', 'attempts', 'pauses', 'audit'):
        db.execute('CREATE TABLE ' + table + ' (value TEXT)')
    db.commit()
    db.close()
    files = {n: b'{}' for n in ('execution_permission.json', 'prior_run_guard.json')}
    files['reviewed_plan.json'] = json.dumps(plan).encode()
    files['run_manifest.json'] = json.dumps({'github_run_id': str(recovery.RUN), 'github_commit': recovery.COMMIT,
        'synthetic_data': False, 'expected_programs': 16, 'provider': 'xAI', 'excluded_from_main': True}).encode()
    files['account_access.json'] = json.dumps({'billing_verified': False, 'model_generation_calls': 0,
        'models': [{'http_status': 400, 'passed': False, 'requested_model': 'grok-4.7', 'returned_model': None}],
        'passed': False, 'synthetic_data': False}).encode()
    files['spending.sqlite'] = dbpath.read_bytes()
    metadata = {'id': recovery.ARTIFACT, 'name': f'xai-validation-{recovery.RUN}-final',
        'workflow_run': {'id': recovery.RUN, 'head_sha': recovery.COMMIT}}
    steps = [{'name': 'Verify exact model metadata without generation', 'conclusion': 'failure'},
             {'name': 'Verify every output and record validation-only usage', 'conclusion': 'skipped'}]
    steps += [{'name': f'Generate excluded validation group {i}', 'conclusion': 'skipped'} for i in range(16)]
    jobs = {'jobs': [{'name': 'xai-validation', 'run_id': recovery.RUN, 'head_sha': recovery.COMMIT,
                     'run_attempt': 1, 'status': 'completed', 'conclusion': 'failure', 'steps': steps}]}
    def build():
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as z:
            for name, data in files.items():
                z.writestr('xai_api_validation/' + name, data)
            z.writestr('xai_prior_guard.json', b'{}')
        data = output.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        monkeypatch.setattr(recovery, 'ARCHIVE_SHA256', digest)
        metadata['digest'] = 'sha256:' + digest
        return data
    return files, metadata, jobs, dbpath, build


def test_zero_request_failure_can_be_verified(previous):
    files, metadata, jobs, dbpath, build = previous
    proof = recovery.verify_previous(build(), metadata, jobs)
    assert proof['previous_generation_calls'] == 0 and proof['only_original_unfilled_slots'] == 16
    assert proof['original_plan_unchanged'] and proof['new_main_slots'] == 0


@pytest.mark.parametrize('table', ['slots', 'attempts', 'pauses', 'audit'])
def test_any_previous_request_or_spending_state_blocks(previous, table):
    files, metadata, jobs, dbpath, build = previous
    db = sqlite3.connect(dbpath)
    db.execute('INSERT INTO ' + table + ' VALUES (?)', ('previous-state',))
    db.commit()
    db.close()
    files['spending.sqlite'] = dbpath.read_bytes()
    with pytest.raises(DispatchPaused, match='request or spending'):
        recovery.verify_previous(build(), metadata, jobs)


@pytest.mark.parametrize('outcome', ['success', 'failure', 'cancelled', None])
def test_any_unskipped_generation_step_blocks(previous, outcome):
    files, metadata, jobs, dbpath, build = previous
    jobs['jobs'][0]['steps'][-1]['conclusion'] = outcome
    with pytest.raises(DispatchPaused, match='skipped'):
        recovery.verify_previous(build(), metadata, jobs)


def test_extra_source_or_journal_blocks(previous):
    files, metadata, jobs, dbpath, build = previous
    files['request.json'] = b'{}'
    with pytest.raises(DispatchPaused, match='unexpected'):
        recovery.verify_previous(build(), metadata, jobs)


def test_recovery_marker_blocks_even_if_expired():
    with pytest.raises(DispatchPaused, match='already has saved state'):
        recovery.check_inventory([{'total_count': 1, 'artifacts': [{'expired': True}]}], recovery=True)


def test_recovery_not_allowed_on_main_or_rerun(tmp_path, monkeypatch):
    monkeypatch.setenv('GITHUB_REPOSITORY', 'agrawal-priyank/depfailbench')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '2')
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/main')
    monkeypatch.setenv('CONFIRM_PAID_GENERATION', 'true')
    with pytest.raises(DispatchPaused, match='first-attempt'):
        recovery.prepare(tmp_path / 'state')
    assert not (tmp_path / 'state').exists()


def test_workflow_recovery_selects_only_xai_without_other_execution_modes():
    source = (Path(__file__).parents[1] / '.github/workflows/full-study.yml').read_text()
    start = source.index('  xai-validation:')
    end = source.index('  saved-openai-evaluation:', start)
    xai = source[start:end]
    assert 'inputs.recover_grok_after_key_fix && !inputs.confirm_paid_generation' in xai
    assert 'recover_xai_metadata_failure.py' in xai and recovery.MARKER in xai
    proof = xai[xai.index('      - name: Prove the previous Grok'):xai.index('      - name: Save the stable prepared marker')]
    assert 'GH_TOKEN:' in proof and 'API_KEY' not in proof
    for name in ('mistral-validation', 'google-validation', 'saved-openai-evaluation', 'verify-remaining-setup', 'inspect-grok-access'):
        body = source.split('  ' + name + ':', 1)[1].split('    runs-on:', 1)[0]
        assert '!inputs.recover_grok_after_key_fix' in body
