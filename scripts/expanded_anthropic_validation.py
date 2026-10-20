"""Run the sixteen excluded Anthropic validation slots, never the main cohort.

The default command is a mock rehearsal. Live preparation requires an explicit
confirmation and a positive numeric limit, capped by the reviewed $6 plan.
One slot per process permits an external checkpoint after every response.
"""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
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
PLAN_PATH = SCRIPT.with_name('expanded_anthropic_validation_plan.json')


def load_plan():
    plan = json.loads(PLAN_PATH.read_text())
    if plan['driver_sha256'] != hashlib.sha256(SCRIPT.read_bytes()).hexdigest():
        raise DispatchPaused('validation driver differs from the reviewed plan')
    if plan['snapshot'] != execution_snapshot():
        raise DispatchPaused('study implementation differs from the Linux-validated snapshot')
    slots = [s for s in allocation()[1] if s['provider'] == 'Anthropic']
    if plan['slots'] != slots or len(slots) != 16 or any(s['cohort'] != 'validation' for s in slots):
        raise DispatchPaused('Anthropic validation allocation differs from the reviewed sixteen slots')
    if plan['maximum_cost_usd'] != '6' or plan['per_attempt_allowance_usd'] != '0.35':
        raise DispatchPaused('reviewed pilot limits changed')
    return plan


def prepare(destination, *, maximum_cost_usd, live=False):
    plan = load_plan()
    limit = Decimal(maximum_cost_usd)
    if not limit.is_finite() or not 0 < limit <= Decimal(plan['maximum_cost_usd']):
        raise DispatchPaused('positive execution ceiling at or below the reviewed $6 limit required')
    if live and (os.environ.get('CONFIRM_PAID_GENERATION') != 'true' or os.environ.get('GITHUB_RUN_ATTEMPT') != '1'):
        raise DispatchPaused('live execution requires confirmation and an original workflow attempt')
    expiry = datetime.fromisoformat(plan['authorization_valid_until_utc'])
    if live and expiry <= datetime.now(timezone.utc):
        raise DispatchPaused('the reviewed paid-pilot authorization window has expired')
    destination.mkdir(parents=True, exist_ok=False)
    save_json(destination / 'reviewed_plan.json', plan)
    save_json(destination / 'run_manifest.json', {
        'cohort': 'validation', 'provider': 'Anthropic', 'expected_programs': 16,
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
        'allowed_providers': ['Anthropic'],
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
    if d.get('allowed_providers') != ['Anthropic'] or d.get('allowed_artifact_ids') != [s['artifact_id'] for s in plan['slots']] or \
            d.get('driver_sha256') != plan['driver_sha256']:
        raise DispatchPaused('batch authorization scope differs')
    if manifest['synthetic_data'] != (d['execution_mode'] == 'mock_validation'):
        raise DispatchPaused('batch simulation mode differs from permission')
    ledger = SpendingLedger(destination / 'spending.sqlite', limit_usd=manifest['maximum_cost_usd'],
                            simulation_only=False, authorization=permit)
    return plan, manifest, permit, ledger


def credential(provider):
    if provider != 'Anthropic':
        raise DispatchPaused('this batch permits only Anthropic credentials')
    return environment_credential(provider)


class ScopedGenerator(LiveGenerator):
    def authorize_slot(self, slot):
        plan = load_plan()
        if slot not in plan['slots'] or slot['provider'] != 'Anthropic' or slot['cohort'] != 'validation':
            raise DispatchPaused('slot is outside the exact excluded Anthropic batch')
        super().authorize_slot(slot)


async def access_check(destination):
    plan, manifest, permit, ledger = context(destination)
    if manifest['synthetic_data']:
        raise DispatchPaused('synthetic credentials cannot establish account access')
    key = credential('Anthropic')
    model = 'claude-sonnet-5-5'
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False,
            timeout=30, transport=httpx.AsyncHTTPTransport(retries=0, trust_env=False)) as client:
        response = await client.get('https://api.anthropic.com/v1/models/' + model,
            headers={'x-api-key': key, 'anthropic-version': '2023-06-01'})
    passed = False
    if response.status_code == 200:
        returned = response.json().get('id', '')
        passed = isinstance(returned, str) and (returned == model or returned.startswith(model + '-'))
    report = {'passed': passed, 'http_status': response.status_code,
              'requested_model': model, 'model_generation_calls': 0, 'billing_verified': False}
    save_json(destination / 'account_access.json', report)
    if not passed:
        raise DispatchPaused('Anthropic model-metadata access failed; inspect status without generating')
    return report


async def generate_slot(destination, index, *, mock_transport=None, mock_credential=None):
    plan, manifest, permit, ledger = context(destination)
    if type(index) is not int or not 0 <= index < 16:
        raise DispatchPaused('slot index must be one of the sixteen declared validation coordinates')
    slot = plan['slots'][index]
    if not manifest['synthetic_data'] and not json.loads((destination / 'account_access.json').read_text())['passed']:
        raise DispatchPaused('successful model-metadata access is required before paid generation')
    if (destination / 'artifacts' / slot['artifact_id']).exists():
        raise DispatchPaused('slot evidence already exists; recover and review it without reissuing')
    rates = {k: TokenRates(**v) for k, v in plan['token_rates'].items()}
    async with ScopedGenerator(output=destination / 'artifacts', ledger=ledger, rates=rates,
            authorization=permit, credential_loader=mock_credential or credential,
            wire_transport=mock_transport) as generator:
        row = await generator.generate(slot, allowance_usd=plan['per_attempt_allowance_usd'])
    save_json(destination / f'checkpoint_{index:02d}.json', {
        'artifact_id': slot['artifact_id'], 'generation_status': row['generation_status'],
        'synthetic_data': manifest['synthetic_data'], 'ledger': ledger.snapshot()})
    return row


async def generate_pair(destination, index, *, mock_transport=None, mock_credential=None):
    if type(index) is not int or not 0 <= index < 8:
        raise DispatchPaused('pair index must be within the eight declared validation pairs')
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
    report = {'complete': True, 'programs': 16, 'provider': 'Anthropic', 'cohort': 'validation',
        'excluded_from_main': True, 'synthetic_data': manifest['synthetic_data'],
        'model_generation_calls': 0 if manifest['synthetic_data'] else len(totals['attempts']),
        'estimated_token_cost_usd': str(Decimal(totals['cost']) / Decimal(totals['units_per_usd'])),
        'invoice_cost_verified': False, 'rows': rows, 'ledger': totals}
    save_json(destination / 'summary.json', report)
    return {k: v for k, v in report.items() if k not in {'rows', 'ledger'}}


async def mock_rehearsal(destination):
    prepare(destination, maximum_cost_usd='6', live=False)
    calls = []
    canary = 'SYNTHETIC-ANTHROPIC-BATCH-CANARY-NOT-A-REAL-KEY'
    def handler(request):
        assert str(request.url) == 'https://api.anthropic.com/v1/messages'
        assert request.headers['x-api-key'] == canary
        body = json.loads(request.content)
        assert body['model'] == 'claude-sonnet-5-5'
        calls.append(body)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
            content=sse_bytes(stream_events('Anthropic', fixture('Anthropic', body['model']))), request=request)
    for index in range(8):
        await generate_pair(destination, index, mock_transport=httpx.MockTransport(handler), mock_credential=lambda p: canary)
    try:
        await generate_slot(destination, 0, mock_transport=httpx.MockTransport(handler), mock_credential=lambda p: canary)
    except DispatchPaused:
        pass
    else:
        raise AssertionError('duplicate dispatch was not blocked')
    assert len(calls) == 16
    for p in destination.rglob('*'):
        if p.is_file():
            assert canary.encode() not in p.read_bytes()
    return {**summarize(destination), 'mock_wire_calls': len(calls), 'duplicate_dispatch_blocked': True,
            'credential_canary_absent': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'access', 'slot', 'pair', 'summarize', 'mock-rehearsal'])
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--maximum-cost-usd', default='0')
    parser.add_argument('--index', type=int)
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            prepare(args.state, maximum_cost_usd=args.maximum_cost_usd, live=True)
            result = {'prepared': True, 'provider': 'Anthropic', 'cohort': 'validation', 'programs': 16}
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
