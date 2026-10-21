"""Compare repeats while retaining literal traces and internal key relationships.

Only E5's stored internal idempotency_key UUID may be alpha-renamed. Public
values, receipts, effects and all other application state remain literal.
"""
from copy import deepcopy
from uuid import UUID

POLICY = 'linked-internal-payment-uuid-2026-10-20'


def literal_view(result):
    return {'clean_qualified': result['clean_qualified'], 'primary_pass': result['primary_pass'],
        'generation_failure': result.get('generation_failure'), 'integrity_error': result.get('integrity_error'),
        'observations': [{'scenario': o['scenario'], 'pass': o['pass'], 'outcome_class': o.get('outcome_class'),
            'watchdog_intervened': o.get('watchdog_intervened', False),
            'responses': [{'status': r['status'], 'successful_body': r.get('body') if r['status'] == 200 else None}
                          for r in o.get('responses', [])],
            'effects': (o.get('dependency') or {}).get('effects', []),
            'objects': (o.get('dependency') or {}).get('objects', {}),
            'preferences': (o.get('dependency') or {}).get('preferences', {}),
            'stock': (o.get('dependency') or {}).get('stock', {}),
            'application_state': o.get('application_state', {})} for o in result.get('observations', [])]}


def is_uuid(value):
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value.lower()
    except (ValueError, AttributeError):
        return False


def behavior_view(result):
    """Create a comparison-only copy; never alter the recorded evidence."""
    view = deepcopy(literal_view(result))
    if result.get('task') != 'E5':
        return view
    for original, compared in zip(result.get('observations', []), view['observations']):
        attempts = (original.get('dependency') or {}).get('attempts', [])
        aliases = {}
        # First-occurrence labels preserve key equality/inequality across all
        # retries and public requests inside this one independently run probe.
        for attempt in attempts:
            key = attempt.get('idempotency_key')
            if is_uuid(key) and key not in aliases:
                aliases[key] = len(aliases)
        orders = compared['application_state'].get('orders', {})
        normalized = False
        if isinstance(orders, dict):
            for record in orders.values():
                if isinstance(record, dict):
                    key = record.get('idempotency_key')
                    if is_uuid(key) and key in aliases:
                        record['idempotency_key'] = {'internal_uuid_alias': aliases[key]}
                        normalized = True
        if normalized:
            compared['idempotency_key_relationships'] = [
                {'public_index': a.get('public_index'), 'method': a.get('method'),
                 'path': a.get('path'), 'operation': a.get('operation'),
                 'payload': deepcopy(a.get('payload')),
                 'key': {'internal_uuid_alias': aliases[a['idempotency_key']]}
                        if is_uuid(a.get('idempotency_key')) else {'literal': a.get('idempotency_key')}}
                for a in attempts]
    return view
