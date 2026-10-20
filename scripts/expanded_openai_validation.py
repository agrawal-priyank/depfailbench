"""Run the sixty-four excluded OpenAI validation slots, never the main cohort.

The default command is a mock rehearsal. Live preparation requires an explicit
confirmation and a positive numeric limit, capped by the scoped $8 plan. The author authorized advancing validation within the
earlier API budget; $8 is a conservative operational limit, not a new main budget.
One slot per process permits an external checkpoint after every response.
"""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
import subprocess
from pathlib import Path

import httpx

from benchmark.expanded.collect import artifact_manifest
from benchmark.expanded.execution_authorization import ExecutionPermit, execution_snapshot
from benchmark.expanded.live_generation import LiveGenerator
from benchmark.expanded.live_transport import environment_credential
from benchmark.expanded.planning import allocation, assets_root
from benchmark.expanded.provider_dry_run import fixture, sse_bytes, stream_events
from benchmark.expanded.provider_generation import save_json
from benchmark.expanded.providers import TokenRates, sha256
from benchmark.expanded.spending import DispatchPaused, SpendingLedger

SCRIPT = Path(__file__).resolve()
PLAN_PATH = SCRIPT.with_name('expanded_openai_validation_plan.json')


def load_plan():
    plan = json.loads(PLAN_PATH.read_text())
    if plan['driver_sha256'] != hashlib.sha256(SCRIPT.read_bytes()).hexdigest():
        raise DispatchPaused('validation driver differs from the reviewed plan')
    if plan['batch_id'] != 'openai-validation-20261020-v1' or plan['prepared_artifact_name'] != 'openai-validation-20261020-v1-prepared':
        raise DispatchPaused('reviewed batch identity changed')
    if plan['snapshot'] != execution_snapshot():
        raise DispatchPaused('study implementation differs from the Linux-validated snapshot')
    slots = [s for s in allocation()[1] if s['provider'] == 'OpenAI']
    if plan['slots'] != slots or len(slots) != 64 or any(s['cohort'] != 'validation' for s in slots):
        raise DispatchPaused('OpenAI validation allocation differs from the reviewed sixty-four slots')
    if plan['maximum_cost_usd'] != '8' or plan['per_attempt_allowance_usd'] != {'gpt-6.1-sol': '0.35', 'gpt-6-luna': '0.025'}:
        raise DispatchPaused('reviewed pilot limits changed')
    return plan


def prior_run_check(destination):
    """Check artifact metadata only; serialize this step using workflow concurrency.

    The stable prepared marker is uploaded before any provider authentication.
    Expired or previous failed runs also block silent replacement generation.
    """
    plan = load_plan()
    if os.environ.get('GITHUB_REPOSITORY') != 'agrawal-priyank/depfailbench' or os.environ.get('GITHUB_RUN_ATTEMPT') != '1':
        raise DispatchPaused('original repository workflow required')
    if not os.environ.get('GITHUB_RUN_ID') or not os.environ.get('GITHUB_SHA'):
        raise DispatchPaused('workflow identity required')
    result = subprocess.run(['gh', 'api', '--paginate', '--slurp',
        'repos/agrawal-priyank/depfailbench/actions/artifacts?per_page=100'],
        capture_output=True, text=True, check=False)
    if result.returncode:
        raise DispatchPaused('prior batch metadata could not be verified')
    pages = json.loads(result.stdout)
    artifacts = [a for page in pages for a in page['artifacts']]
    if not pages or any(page['total_count'] != len(artifacts) for page in pages):
        raise DispatchPaused('incomplete or changing prior artifact inventory')
    if any(a['name'] == plan['prepared_artifact_name'] for a in artifacts):
        raise DispatchPaused('this validation batch already has saved state; recover it rather than dispatch again')
    guard = {'clear': True, 'batch_id': plan['batch_id'],
        'plan_sha256': hashlib.sha256(PLAN_PATH.read_bytes()).hexdigest(),
        'github_run_id': os.environ['GITHUB_RUN_ID'], 'github_commit': os.environ['GITHUB_SHA'],
        'checked_at_utc': datetime.now(timezone.utc).isoformat(),
        'prior_artifacts_checked': len(artifacts), 'model_generation_calls': 0}
    if destination.exists():
        raise DispatchPaused('prior-run guard already exists')
    save_json(destination, guard)
    return guard


def validate_prior_run_guard(path, *, check_age=True):
    plan = load_plan()
    if path is None or not path.is_file():
        raise DispatchPaused('verified prior batch check required before live preparation')
    guard = json.loads(path.read_text())
    if guard.get('clear') is not True or guard.get('batch_id') != plan['batch_id'] or \
            guard.get('plan_sha256') != hashlib.sha256(PLAN_PATH.read_bytes()).hexdigest() or \
            guard.get('github_run_id') != os.environ.get('GITHUB_RUN_ID') or \
            guard.get('github_commit') != os.environ.get('GITHUB_SHA'):
        raise DispatchPaused('prior batch check does not match this plan and workflow')
    checked = datetime.fromisoformat(guard['checked_at_utc'])
    age = datetime.now(timezone.utc) - checked
    if checked.tzinfo is None or age.total_seconds() < 0 or (check_age and age > timedelta(hours=1)):
        raise DispatchPaused('prior batch check is stale or invalid')


def prepare(destination, *, maximum_cost_usd, live=False, guard_path=None):
    plan = load_plan()
    limit = Decimal(maximum_cost_usd)
    if not limit.is_finite() or not 0 < limit <= Decimal(plan['maximum_cost_usd']):
        raise DispatchPaused('positive execution ceiling at or below the reviewed $8 limit required')
    if live and (os.environ.get('CONFIRM_PAID_GENERATION') != 'true' or os.environ.get('GITHUB_RUN_ATTEMPT') != '1'):
        raise DispatchPaused('live execution requires confirmation and an original workflow attempt')
    expiry = datetime.fromisoformat(plan['authorization_valid_until_utc'])
    if live and expiry <= datetime.now(timezone.utc):
        raise DispatchPaused('the reviewed paid-pilot authorization window has expired')
    if live:
        validate_prior_run_guard(guard_path)
    destination.mkdir(parents=True, exist_ok=False)
    if live:
        save_json(destination / 'prior_run_guard.json', json.loads(guard_path.read_text()))
    save_json(destination / 'reviewed_plan.json', plan)
    save_json(destination / 'run_manifest.json', {
        'cohort': 'validation', 'provider': 'OpenAI', 'expected_programs': 64,
        'excluded_from_main': True, 'plan_sha256': hashlib.sha256(PLAN_PATH.read_bytes()).hexdigest(),
        'driver_sha256': plan['driver_sha256'], 'maximum_cost_usd': str(limit),
        'synthetic_data': not live, 'github_run_id': os.environ.get('GITHUB_RUN_ID'),
        'github_commit': os.environ.get('GITHUB_SHA'),
        'interruption_policy': 'Restore saved evidence and review any unfilled slot; never silently reissue a request.'})
    permission = {
        'schema_version': 1, 'execution_mode': 'live' if live else 'mock_validation',
        'mock_validation_authorized': not live, 'paid_execution_authorized': live,
        'cohort': 'validation', 'authorized_by': plan['authorized_by'] if live else 'synthetic rehearsal',
        'authorization_record': plan['authorization_record'] if live else 'mock wire only; no actual expenditure',
        'maximum_cost_usd': str(limit),
        'expires_at_utc': min(datetime.now(timezone.utc) + timedelta(hours=24), expiry).isoformat() if live
            else (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        'snapshot': plan['snapshot'], 'token_rates': plan['token_rates'],
        'allowed_providers': ['OpenAI'],
        'allowed_artifact_ids': [s['artifact_id'] for s in plan['slots']],
        'driver_sha256': plan['driver_sha256']}
    save_json(destination / 'execution_permission.json', permission)
    permit = ExecutionPermit(destination / 'execution_permission.json')
    SpendingLedger(destination / 'spending.sqlite', limit_usd=str(limit), simulation_only=False, authorization=permit)


def context(destination):
    plan = load_plan()
    manifest = json.loads((destination / 'run_manifest.json').read_text())
    if manifest['plan_sha256'] != hashlib.sha256(PLAN_PATH.read_bytes()).hexdigest() or \
            json.loads((destination / 'reviewed_plan.json').read_text()) != plan:
        raise DispatchPaused('stored batch plan changed')
    permit = ExecutionPermit(destination / 'execution_permission.json')
    d = permit.document
    if not manifest['synthetic_data']:
        validate_prior_run_guard(destination / 'prior_run_guard.json', check_age=False)
        if manifest['github_run_id'] != os.environ.get('GITHUB_RUN_ID') or manifest['github_commit'] != os.environ.get('GITHUB_SHA'):
            raise DispatchPaused('stored batch belongs to a different workflow run or commit')
    if d.get('allowed_providers') != ['OpenAI'] or d.get('allowed_artifact_ids') != [s['artifact_id'] for s in plan['slots']] or \
            d.get('driver_sha256') != plan['driver_sha256']:
        raise DispatchPaused('batch authorization scope differs')
    if manifest['synthetic_data'] != (d['execution_mode'] == 'mock_validation'):
        raise DispatchPaused('batch simulation mode differs from permission')
    ledger = SpendingLedger(destination / 'spending.sqlite', limit_usd=manifest['maximum_cost_usd'],
                            simulation_only=False, authorization=permit)
    return plan, manifest, permit, ledger


def credential(provider):
    if provider != 'OpenAI':
        raise DispatchPaused('this batch permits only OpenAI credentials')
    return environment_credential(provider)


class ScopedGenerator(LiveGenerator):
    def authorize_slot(self, slot):
        plan = load_plan()
        if slot not in plan['slots'] or slot['provider'] != 'OpenAI' or slot['cohort'] != 'validation':
            raise DispatchPaused('slot is outside the exact excluded OpenAI batch')
        super().authorize_slot(slot)


async def access_check(destination, *, mock_transport=None, mock_credential=None):
    plan, manifest, permit, ledger = context(destination)
    if manifest['synthetic_data'] and mock_transport is None:
        raise DispatchPaused('synthetic credentials cannot establish account access')
    if not manifest['synthetic_data'] and mock_transport is not None:
        raise DispatchPaused('mock metadata cannot establish real account access')
    key = (mock_credential or credential)('OpenAI')
    rows = []
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False,
            timeout=30, transport=mock_transport or httpx.AsyncHTTPTransport(retries=0, trust_env=False)) as client:
        for model in sorted({s['model_id'] for s in plan['slots']}):
            response = await client.get('https://api.openai.com/v1/models/' + model,
                                        headers={'Authorization': 'Bearer ' + key})
            returned = response.json().get('id', '') if response.status_code == 200 else None
            passed = response.status_code == 200 and isinstance(returned, str) and (returned == model or returned.startswith(model + '-'))
            rows.append({'passed': passed, 'http_status': response.status_code,
                         'requested_model': model, 'returned_model': returned})
    report = {'passed': all(r['passed'] for r in rows), 'models': rows,
              'synthetic_data': manifest['synthetic_data'], 'model_generation_calls': 0, 'billing_verified': False}
    save_json(destination / 'account_access.json', report)
    if not report['passed']:
        raise DispatchPaused('OpenAI model-metadata access failed; inspect status without generating')
    return report


async def generate_slot(destination, index, *, mock_transport=None, mock_credential=None):
    plan, manifest, permit, ledger = context(destination)
    if type(index) is not int or not 0 <= index < 64:
        raise DispatchPaused('slot index must be one of the sixty-four declared validation coordinates')
    slot = plan['slots'][index]
    if not manifest['synthetic_data']:
        access = json.loads((destination / 'account_access.json').read_text())
        if access.get('synthetic_data') is not False or access.get('passed') is not True or not any(
                r['passed'] and r['requested_model'] == slot['model_id'] for r in access['models']):
            raise DispatchPaused('successful real model-metadata access required before generation')
    if (destination / 'artifacts' / slot['artifact_id']).exists():
        raise DispatchPaused('slot evidence already exists; recover and review it without reissuing')
    rates = {k: TokenRates(**v) for k, v in plan['token_rates'].items()}
    async with ScopedGenerator(output=destination / 'artifacts', ledger=ledger, rates=rates,
            authorization=permit, credential_loader=mock_credential or credential,
            wire_transport=mock_transport) as generator:
        row = await generator.generate(slot, allowance_usd=plan['per_attempt_allowance_usd'][slot['model_id']])
    save_json(destination / f'checkpoint_{index:02d}.json', {
        'artifact_id': slot['artifact_id'], 'generation_status': row['generation_status'],
        'synthetic_data': manifest['synthetic_data'], 'ledger': ledger.snapshot()})
    return row


async def generate_pair(destination, index, *, mock_transport=None, mock_credential=None):
    if type(index) is not int or not 0 <= index < 32:
        raise DispatchPaused('pair index must be within the thirty-two declared validation pairs')
    rows = await asyncio.gather(*(generate_slot(destination, 2 * index + offset,
        mock_transport=mock_transport, mock_credential=mock_credential) for offset in (0, 1)), return_exceptions=True)
    if any(isinstance(row, BaseException) for row in rows):
        raise DispatchPaused('one or more slots paused; both requests have stopped and require review')
    return [{k: row[k] for k in ('artifact_id', 'generation_status', 'estimated_token_cost_usd')} for row in rows]


def summarize(destination):
    plan, manifest, permit, ledger = context(destination)
    rows = []
    configurations = {c['id']: c for c in json.loads((assets_root() / 'study.json').read_text())['configurations']}
    for slot in plan['slots']:
        directory = destination / 'artifacts' / slot['artifact_id']
        metadata = json.loads((directory / 'metadata.json').read_text())
        if not manifest['synthetic_data']:
            artifact_manifest(directory, slot, configurations[slot['configuration_id']], assets_root())
        else:
            assert metadata['synthetic_data'] and metadata['artifact_id'] == slot['artifact_id']
            assert sha256((directory / 'app.py').read_text()) == metadata['source_sha256']
        rows.append({'artifact_id': slot['artifact_id'], 'generation_status': metadata['generation_status'],
            'estimated_token_cost_usd': metadata['estimated_token_cost_usd'], 'usage': metadata['provider_usage']})
    totals = ledger.snapshot()
    if totals['held'] or totals['pauses'] or any(a['state'] != 'settled' for a in totals['attempts']):
        raise DispatchPaused('pending financial or execution review prevents a completed-batch claim')
    report = {'complete': True, 'programs': 64, 'provider': 'OpenAI', 'cohort': 'validation',
        'excluded_from_main': True, 'synthetic_data': manifest['synthetic_data'],
        'model_generation_calls': 0 if manifest['synthetic_data'] else len(totals['attempts']),
        'estimated_token_cost_usd': str(Decimal(totals['cost']) / Decimal(totals['units_per_usd'])),
        'invoice_cost_verified': False, 'rows': rows, 'ledger': totals}
    save_json(destination / 'summary.json', report)
    return {k: v for k, v in report.items() if k not in {'rows', 'ledger'}}


async def mock_rehearsal(destination):
    prepare(destination, maximum_cost_usd='8', live=False)
    calls = []
    canary = 'SYNTHETIC-OPENAI-BATCH-CANARY-NOT-A-REAL-KEY'
    def handler(request):
        assert str(request.url) == 'https://api.openai.com/v1/responses'
        assert request.headers['authorization'] == 'Bearer ' + canary
        body = json.loads(request.content)
        assert body['model'] in {'gpt-6.1-sol', 'gpt-6-luna'}
        assert body['reasoning']['mode'] == 'standard'
        assert body['max_output_tokens'] == 32000 and body['tools'] == []
        assert 'temperature' not in body and 'top_p' not in body
        calls.append(body)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
            content=sse_bytes(stream_events('OpenAI', fixture('OpenAI', body['model']))), request=request)
    for index in range(32):
        await generate_pair(destination, index, mock_transport=httpx.MockTransport(handler), mock_credential=lambda p: canary)
    try:
        await generate_slot(destination, 0, mock_transport=httpx.MockTransport(handler), mock_credential=lambda p: canary)
    except DispatchPaused:
        pass
    else:
        raise AssertionError('duplicate dispatch was not blocked')
    assert len(calls) == 64
    for p in destination.rglob('*'):
        if p.is_file():
            assert canary.encode() not in p.read_bytes()
    return {**summarize(destination), 'mock_wire_calls': len(calls), 'duplicate_dispatch_blocked': True,
            'credential_canary_absent': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prior-run-check', 'prepare', 'access', 'slot', 'pair', 'summarize', 'mock-rehearsal'])
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--maximum-cost-usd', default='0')
    parser.add_argument('--index', type=int)
    parser.add_argument('--guard', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'prior-run-check':
            result = prior_run_check(args.state)
        elif args.command == 'prepare':
            prepare(args.state, maximum_cost_usd=args.maximum_cost_usd, live=True, guard_path=args.guard)
            result = {'prepared': True, 'provider': 'OpenAI', 'cohort': 'validation', 'programs': 64}
        elif args.command == 'access': result = asyncio.run(access_check(args.state))
        elif args.command == 'slot':
            row = asyncio.run(generate_slot(args.state, args.index))
            result = {k: row[k] for k in ('artifact_id', 'generation_status', 'estimated_token_cost_usd')}
        elif args.command == 'pair': result = asyncio.run(generate_pair(args.state, args.index))
        elif args.command == 'summarize': result = summarize(args.state)
        else: result = asyncio.run(mock_rehearsal(args.state))
        print(json.dumps(result), flush=True)
    except Exception as exc:
        # Never print HTTP request/response objects, provider bodies or credentials.
        print(json.dumps({'execution_stopped': True, 'error_type': type(exc).__name__,
                          'requires_operator_review': True}), flush=True)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
