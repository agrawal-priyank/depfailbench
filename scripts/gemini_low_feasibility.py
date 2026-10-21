"""Exactly two approved Gemini low-thinking validation coordinates; no main run."""
import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from benchmark.expanded.execution_authorization import ExecutionPermit, execution_snapshot
from benchmark.expanded.live_generation import LiveGenerator
from benchmark.expanded.planning import allocation, assets_root, check
from benchmark.expanded.provider_generation import save_json
from benchmark.expanded.providers import TokenRates, build_request
from benchmark.expanded.spending import DispatchPaused, SpendingLedger

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'scripts/gemini_low_feasibility_plan.json'
MARKER = 'gemini-low-feasibility-20261020-v1-prepared'


def load(path):
    return json.loads(Path(path).read_text())


def require(ok, message):
    if not ok:
        raise DispatchPaused(message)


def candidate_study(original):
    result = json.loads(json.dumps(original))
    config = next(c for c in result['configurations'] if c['provider'] == 'Google')
    require(config['id'] == 'gemini_3_8_flash' and config['generation_settings']['thinking_level'] == 'medium', 'original Gemini setting differs')
    config['id'] = 'gemini_3_8_flash_low'
    config['generation_settings']['thinking_level'] = 'low'
    require(not result['frozen'] and not result['paid_execution_authorized'], 'main must remain disabled')
    return result


def load_plan():
    plan = load(PLAN)
    require(plan['author_approved'] is True and plan['maximum_cost_usd'] == '0.50' and plan['per_request_allowance_usd'] == '0.25', 'specific two-response approval required')
    require(plan['driver_sha256'] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'driver changed')
    require(plan['snapshot'] == execution_snapshot(), 'reviewed current setup changed')
    require(plan['coordinates'] == [['E1', 'C0'], ['E5', 'C1']], 'outside exact approved coordinates')
    return plan


def workflow_identity():
    require(os.environ.get('GITHUB_REPOSITORY') == 'agrawal-priyank/depfailbench' and os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'original repository workflow required')
    require(os.environ.get('GITHUB_REF') == 'refs/heads/array-revision-linux-validation', 'revision branch required')
    require(bool(os.environ.get('GITHUB_RUN_ID') and os.environ.get('GITHUB_SHA')), 'workflow identity missing')


def prior_run_check(path):
    load_plan()
    workflow_identity()
    require(not path.exists(), 'prior-run guard already exists')
    q = subprocess.run(['gh', 'api', '--paginate', '--slurp', 'repos/agrawal-priyank/depfailbench/actions/artifacts?per_page=100&name=' + MARKER], capture_output=True, text=True)
    require(q.returncode == 0, 'prior artifact inventory unavailable')
    pages = json.loads(q.stdout)
    require(bool(pages) and all(p['total_count'] == 0 and not p['artifacts'] for p in pages), 'sample already prepared; recover saved evidence rather than repeat')
    path.parent.mkdir(parents=True, exist_ok=True)
    save_json(path, {'clear': True, 'run': os.environ['GITHUB_RUN_ID'], 'commit': os.environ['GITHUB_SHA'], 'plan_sha256': hashlib.sha256(PLAN.read_bytes()).hexdigest(), 'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'model_api_calls': 0})


def prepare(state, *, guard=None, mock=False):
    plan = load_plan()
    require(not state.exists(), 'existing preparation must not be overwritten')
    if not mock:
        workflow_identity()
        require(os.environ.get('CONFIRM_GEMINI_LOW_FEASIBILITY') == 'true', 'explicit sample confirmation required')
        require(guard is not None and guard.is_file(), 'prior-run guard required')
        proof = load(guard)
        require(proof['clear'] is True and proof['run'] == os.environ['GITHUB_RUN_ID'] and proof['commit'] == os.environ['GITHUB_SHA'] and proof['plan_sha256'] == hashlib.sha256(PLAN.read_bytes()).hexdigest(), 'guard differs from workflow')
        age = datetime.now(timezone.utc) - datetime.fromisoformat(proof['checked_at_utc'])
        require(0 <= age.total_seconds() <= 3600, 'prior-run guard expired')
    candidate = state / 'candidate_repo/expanded_study'
    shutil.copytree(assets_root(), candidate)
    shutil.copyfile(ROOT / 'requirements.lock', candidate.parent / 'requirements.lock')
    (candidate / 'study.json').write_text(json.dumps(candidate_study(load(assets_root() / 'study.json')), indent=2) + '\n')
    check(candidate)
    slots = [next(s for s in allocation(candidate)[1] if s['configuration_id'] == 'gemini_3_8_flash_low' and [s['task'], s['condition']] == coordinate) for coordinate in plan['coordinates']]
    original_config = next(c for c in load(assets_root() / 'study.json')['configurations'] if c['provider'] == 'Google')
    config = next(c for c in load(candidate / 'study.json')['configurations'] if c['provider'] == 'Google')
    for slot in slots:
        text = (candidate / 'prompts' / (slot['task'] + '_' + slot['condition'] + '.md')).read_text()
        expected = build_request(original_config, text)['body']
        expected['generation_config']['thinking_level'] = 'low'
        require(build_request(config, text)['body'] == expected, 'request differs beyond thinking level')
    permission = {'schema_version': 1, 'execution_mode': 'mock_validation' if mock else 'live', 'mock_validation_authorized': mock, 'paid_execution_authorized': not mock, 'cohort': 'validation', 'authorized_by': 'Priyank Agrawal', 'authorization_record': plan['authorization_record'], 'maximum_cost_usd': '0.50', 'expires_at_utc': (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat(), 'snapshot': execution_snapshot(candidate), 'token_rates': plan['token_rates'], 'allowed_providers': ['Google'], 'allowed_artifact_ids': [s['artifact_id'] for s in slots]}
    save_json(state / 'reviewed_plan.json', plan)
    save_json(state / 'execution_permission.json', permission)
    permit = ExecutionPermit(state / 'execution_permission.json', root=candidate)
    SpendingLedger(state / 'spending.sqlite', limit_usd='0.50', simulation_only=False, authorization=permit)
    save_json(state / 'sample_manifest.json', {'slots': slots, 'github_run_id': os.environ.get('GITHUB_RUN_ID'), 'github_commit': os.environ.get('GITHUB_SHA'), 'synthetic_data': mock, 'driver_sha256': plan['driver_sha256'], 'expected_responses': 2, 'excluded_from_main': True, 'main_outputs': 0, 'no_automatic_follow_on': True})
    return {'prepared': True, 'expected_responses': 2, 'model_api_calls': 0, 'synthetic_data': mock}


async def generate(state, index, *, mock_transport=None, mock_credential=None):
    plan = load_plan()
    require(type(index) is int and index in (0, 1), 'outside the two approved coordinates')
    manifest = load(state / 'sample_manifest.json')
    if manifest['synthetic_data']:
        import httpx
        require(type(mock_transport) is httpx.MockTransport and callable(mock_credential), 'synthetic state requires an explicit mocked wire and credential')
    else:
        workflow_identity()
        require(os.environ.get('CONFIRM_GEMINI_LOW_FEASIBILITY') == 'true', 'explicit sample confirmation required')
        require(manifest['github_run_id'] == os.environ['GITHUB_RUN_ID'] and manifest['github_commit'] == os.environ['GITHUB_SHA'], 'sample workflow differs')
        require(mock_transport is None and mock_credential is None, 'live state cannot substitute a mocked wire')
    require(manifest['driver_sha256'] == plan['driver_sha256'], 'prepared driver differs')
    slot = manifest['slots'][index]
    require([slot['task'], slot['condition']] == plan['coordinates'][index] and slot['configuration_id'] == 'gemini_3_8_flash_low', 'prepared coordinates differ')
    require(not (state / 'artifacts' / slot['artifact_id']).exists(), 'existing attempt/output must not be replaced')
    candidate = state / 'candidate_repo/expanded_study'
    permit = ExecutionPermit(state / 'execution_permission.json', root=candidate)
    require(permit.document['allowed_providers'] == ['Google'] and permit.document['allowed_artifact_ids'] == [s['artifact_id'] for s in manifest['slots']], 'permission scope differs')

    class Scoped(LiveGenerator):
        def authorize_slot(self, value):
            require(value == slot, 'outside this exact permitted response coordinate')
            super().authorize_slot(value)

    ledger = SpendingLedger(state / 'spending.sqlite', limit_usd='0.50', simulation_only=False, authorization=permit)
    rates = {k: TokenRates(**v) for k, v in plan['token_rates'].items()}
    options = {'wire_transport': mock_transport, 'credential_loader': mock_credential} if manifest['synthetic_data'] else {}
    async with Scoped(output=state / 'artifacts', ledger=ledger, rates=rates, authorization=permit, root=candidate, **options) as sender:
        result = await sender.generate(slot, allowance_usd='0.25')
    attempts = [load(p) for p in (state / 'artifacts' / slot['artifact_id']).glob('attempt_*/attempt.json')]
    summary = {'artifact_id': slot['artifact_id'], 'generation_status': result['generation_status'], 'elapsed_generation_s': sum(a['elapsed_s'] for a in attempts), 'estimated_token_cost_usd': result['estimated_token_cost_usd'], 'provider_usage': result['provider_usage'], 'invoice_cost_verified': False, 'synthetic_data': manifest['synthetic_data'], 'functional_tests_performed': False, 'main_outputs': 0}
    save_json(state / ('sample_' + str(index) + '_summary.json'), summary)
    return {k: v for k, v in summary.items() if k != 'provider_usage'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prior-run-check', 'prepare', 'generate'])
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--guard', type=Path)
    parser.add_argument('--index', type=int)
    args = parser.parse_args()
    try:
        if args.mode == 'prior-run-check':
            prior_run_check(args.state)
            result = {'prior_check_clear': True, 'model_api_calls': 0}
        elif args.mode == 'prepare':
            result = prepare(args.state, guard=args.guard)
        else:
            result = asyncio.run(generate(args.state, args.index))
        print(json.dumps(result), flush=True)
    except Exception as exc:
        print(json.dumps({'stopped': True, 'error_type': type(exc).__name__, 'requires_review': True}), flush=True)
        raise SystemExit(1) from None
