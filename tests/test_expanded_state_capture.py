"""Capture valid string state without changing truth or receipt checks."""
from dataclasses import dataclass
from enum import Enum
import json

from pydantic import BaseModel
import pytest

from benchmark.expanded.contracts import Settings
from benchmark.expanded.oracles import classify
from benchmark.expanded.worker import normalize


class Status(str):
    pass


class StatusEnum(str, Enum):
    RESERVED = 'RESERVED'
    LOWERCASE = 'reserved'


class MisleadingStatus(str):
    def __str__(self):
        return 'RESERVED'


@pytest.mark.parametrize('value,expected', [
    (Status('RESERVED'), 'RESERVED'),
    (StatusEnum.RESERVED, 'RESERVED'),
    (StatusEnum.LOWERCASE, 'reserved'),
    (MisleadingStatus('UNRESOLVED'), 'UNRESOLVED'),
])
def test_string_state_records_underlying_value_without_case_or_truth_changes(value, expected):
    captured = normalize({'request-1': {'status': value}})
    assert type(captured['request-1']['status']) is str
    assert json.loads(json.dumps(captured)) == {'request-1': {'status': expected}}


@pytest.mark.parametrize('value,passes', [
    (Status('RESERVED'), True),
    (StatusEnum.RESERVED, True),
    (StatusEnum.LOWERCASE, False),
    (Status('UNRESOLVED'), False),
    (MisleadingStatus('UNRESOLVED'), False),
])
def test_string_state_capture_retains_external_effect_and_public_receipt_guards(value, passes):
    receipt = {'request_id': 'request-1', 'reservation_id': 'reservation-1',
               'item_id': 'widget', 'quantity': 3, 'status': 'reserved'}
    evidence = {'responses': [{'status': 200, 'body': receipt, 'wall_latency_s': .01}],
                'dependency': {'attempts': [{}], 'effects': [receipt], 'contract_violations': [],
                               'stock': {'widget': 7, 'gadget': 8}},
                'application_state': normalize({'reservations': {'request-1': value}})}
    assert classify('E6', 'clean', Settings(), evidence)['pass'] is passes
    evidence['responses'][0]['body'] = {**receipt, 'reservation_id': 'invented'}
    assert not classify('E6', 'clean', Settings(), evidence)['pass']
    evidence['responses'][0]['body'] = receipt
    evidence['dependency']['effects'] = []
    assert not classify('E6', 'clean', Settings(), evidence)['pass']


def test_existing_record_representations_remain_supported_and_unknown_objects_stay_visible():
    @dataclass
    class DataState:
        status: str

    class ModelState(BaseModel):
        status: str

    class Unknown:
        pass

    assert normalize([DataState('RESERVED'), ModelState(status='RESERVED')]) == [
        {'status': 'RESERVED'}, {'status': 'RESERVED'}]
    assert normalize(Unknown()) == {'unrecognized_state_type': 'Unknown'}
