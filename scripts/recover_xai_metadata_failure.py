"""Resume only the sixteen Grok slots proven untouched by a metadata failure.

This preparation step has no model credentials or generation requests. It keeps
the original batch plan, verifies immutable failed-run evidence, and requires a
new stable marker. The unchanged driver performs all actual generation later.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import zipfile

from benchmark.expanded.provider_generation import save_json
from benchmark.expanded.spending import DispatchPaused

spec = importlib.util.spec_from_file_location('remaining_batch_recovery', Path(__file__).with_name('expanded_remaining_validation.py'))
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)
RUN = 39486369819
COMMIT = '6bf1d89465bf37341030b422fca1bded17b826f8'
ARTIFACT = 12293064213
ARCHIVE_SHA256 = '0f57fbfc0e4350daa3e6fc81a7ca952d221a55c0ce18e69731b2c13b4a03ae4d'
MARKER = 'xai-validation-20261020-v1-metadata-recovery-prepared'
API = 'repos/agrawal-priyank/depfailbench/'


def require(condition, message):
    if not condition:
        raise DispatchPaused(message)


def verify_previous(archive, metadata, jobs):
    batch.select_provider('xAI')
    plan = batch.load_plan()
    require(hashlib.sha256(archive).hexdigest() == ARCHIVE_SHA256, 'previous archive differs')
    require(metadata['id'] == ARTIFACT and metadata['name'] == f'xai-validation-{RUN}-final'
            and metadata['digest'] == 'sha256:' + ARCHIVE_SHA256
            and metadata['workflow_run']['id'] == RUN and metadata['workflow_run']['head_sha'] == COMMIT,
            'previous artifact identity differs')
    selected = [j for j in jobs['jobs'] if j['name'] == 'xai-validation']
    require(len(selected) == 1, 'one previous Grok job required')
    job = selected[0]
    require(job['run_id'] == RUN and job['head_sha'] == COMMIT and job['run_attempt'] == 1
            and job['status'] == 'completed' and job['conclusion'] == 'failure', 'previous job identity differs')
    steps = {s['name']: s['conclusion'] for s in job['steps']}
    require(steps.get('Verify exact model metadata without generation') == 'failure', 'metadata-only failure required')
    require(all(steps.get(f'Generate excluded validation group {i}') == 'skipped' for i in range(16)),
            'all sixteen previous generation steps must have been skipped')
    require(steps.get('Verify every output and record validation-only usage') == 'skipped', 'previous summary unexpectedly ran')
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        expected = {'xai_api_validation/' + n for n in (
            'account_access.json', 'execution_permission.json', 'prior_run_guard.json',
            'reviewed_plan.json', 'run_manifest.json', 'spending.sqlite')} | {'xai_prior_guard.json'}
        require(len(z.namelist()) == len(expected) and set(z.namelist()) == expected,
                'unexpected previous files or request evidence')
        read = lambda name: json.loads(z.read('xai_api_validation/' + name))
        require(read('reviewed_plan.json') == plan, 'original Grok plan must remain unchanged')
        manifest = read('run_manifest.json')
        require(manifest['github_run_id'] == str(RUN) and manifest['github_commit'] == COMMIT
                and manifest['synthetic_data'] is False and manifest['expected_programs'] == 16
                and manifest['provider'] == 'xAI' and manifest['excluded_from_main'] is True,
                'previous manifest differs')
        require(read('account_access.json') == {
            'billing_verified': False, 'model_generation_calls': 0, 'models': [{
                'http_status': 400, 'passed': False, 'requested_model': 'grok-4.7', 'returned_model': None}],
            'passed': False, 'synthetic_data': False}, 'previous access outcome differs')
        with tempfile.TemporaryDirectory() as tmp:
            dbpath = Path(tmp) / 'previous.sqlite'
            dbpath.write_bytes(z.read('xai_api_validation/spending.sqlite'))
            db = sqlite3.connect(dbpath.as_uri() + '?mode=ro', uri=True)
            try:
                require(db.execute('PRAGMA integrity_check').fetchone() == ('ok',), 'previous ledger integrity failed')
                for table in ('slots', 'attempts', 'pauses', 'audit'):
                    require(db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] == 0,
                            'previous ledger contains request or spending evidence')
            finally:
                db.close()
    return {'previous_run_id': RUN, 'previous_commit': COMMIT, 'previous_artifact_id': ARTIFACT,
            'previous_archive_sha256': ARCHIVE_SHA256, 'previous_generation_calls': 0,
            'all_generation_steps_skipped': True, 'original_plan_unchanged': True,
            'only_original_unfilled_slots': 16, 'new_main_slots': 0}


def api(path, *, binary=False):
    result = subprocess.run(['gh', 'api', API + path], capture_output=True, check=False)
    require(result.returncode == 0, 'GitHub recovery evidence unavailable')
    return result.stdout if binary else json.loads(result.stdout)


def check_inventory(pages, *, recovery):
    require(bool(pages), 'artifact inventory missing')
    artifacts = [a for page in pages for a in page['artifacts']]
    require(all(p['total_count'] == len(artifacts) for p in pages), 'artifact inventory changed or incomplete')
    if recovery:
        require(not artifacts, 'Grok recovery already has saved state; do not dispatch again')
    else:
        require(len(artifacts) == 1 and artifacts[0]['name'] == batch.load_plan()['prepared_artifact_name']
                and artifacts[0]['workflow_run']['id'] == RUN
                and artifacts[0]['workflow_run']['head_sha'] == COMMIT, 'original stable marker differs')


def prepare(destination):
    require(os.environ.get('GITHUB_REPOSITORY') == 'agrawal-priyank/depfailbench'
            and os.environ.get('GITHUB_RUN_ATTEMPT') == '1'
            and os.environ.get('GITHUB_REF') == 'refs/heads/array-revision-linux-validation'
            and os.environ.get('CONFIRM_PAID_GENERATION') == 'true'
            and bool(os.environ.get('GITHUB_RUN_ID')) and bool(os.environ.get('GITHUB_SHA')),
            'confirmed first-attempt revision-branch workflow required')
    require(not destination.exists(), 'recovery destination already exists')
    batch.select_provider('xAI')
    plan = batch.load_plan()
    for marker, recovery in ((plan['prepared_artifact_name'], False), (MARKER, True)):
        result = subprocess.run(['gh', 'api', '--paginate', '--slurp', API + 'actions/artifacts?per_page=100&name=' + marker],
                                capture_output=True, text=True, check=False)
        require(result.returncode == 0, 'artifact inventory unavailable')
        check_inventory(json.loads(result.stdout), recovery=recovery)
    metadata = api(f'actions/artifacts/{ARTIFACT}')
    jobs = api(f'actions/runs/{RUN}/jobs?per_page=100')
    archive = api(f'actions/artifacts/{ARTIFACT}/zip', binary=True)
    proof = verify_previous(archive, metadata, jobs)
    guard_path = destination.parent / 'xai_metadata_recovery_guard.json'
    require(not guard_path.exists(), 'recovery guard already exists')
    guard_path.parent.mkdir(parents=True, exist_ok=True)
    guard = {'clear': True, 'batch_id': plan['batch_id'],
             'plan_sha256': hashlib.sha256(batch.PLAN_PATH.read_bytes()).hexdigest(),
             'github_run_id': os.environ['GITHUB_RUN_ID'], 'github_commit': os.environ['GITHUB_SHA'],
             'checked_at_utc': datetime.now(timezone.utc).isoformat(),
             'prior_artifacts_checked': 1, 'model_generation_calls': 0,
             'explicit_metadata_failure_recovery': proof, 'new_stable_marker': MARKER}
    save_json(guard_path, guard)
    batch.prepare(destination, maximum_cost_usd='8', live=True, guard_path=guard_path)
    # Preserve the exact source evidence as well as the independent zero-request proof.
    (destination / 'previous_metadata_failure.zip').write_bytes(archive)
    save_json(destination / 'previous_artifact_metadata.json', metadata)
    save_json(destination / 'previous_run_jobs.json', jobs)
    save_json(destination / 'metadata_recovery_proof.json', proof)
    return proof


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.state)))
    except Exception as error:
        print(json.dumps({'recovery_stopped': True, 'error_type': type(error).__name__, 'generation_calls': 0}))
        raise SystemExit(1) from None
