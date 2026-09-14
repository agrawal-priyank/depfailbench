import asyncio
import json
import sys

from benchmark.artifact_runner import evaluate as evaluate_pilot
from benchmark.full_eval import evaluate as evaluate_full, evaluation_seed


def test_evaluation_seed_is_stable_and_probe_specific():
    assert evaluation_seed('artifact-1', 'clean') == evaluation_seed('artifact-1', 'clean')
    assert evaluation_seed('artifact-1', 'clean') != evaluation_seed('artifact-1', 'timeout')
    assert evaluation_seed('artifact-1', 'clean') != evaluation_seed('artifact-2', 'clean')


def test_dataclass_application_import_uses_normal_module_registration(tmp_path):
    (tmp_path/'metadata.json').write_text(json.dumps({
        'artifact_id': 'loader_regression',
        'task': 'T1',
        'condition': 'C0',
        'model_provider': 'Test',
        'model_family': 'Test',
        'model_version': 'Test',
        'generation_index': 1,
    }))
    (tmp_path/'raw_response.json').write_text('{}')
    (tmp_path/'app.py').write_text('''from __future__ import annotations
from dataclasses import dataclass
import httpx
from fastapi import FastAPI
@dataclass
class Product:
    id: int
    name: str
    price: float
def create_app(transport,settings=None):
    app=FastAPI()
    @app.get('/products/{product_id}',response_model=Product)
    async def product(product_id:int):
        async with httpx.AsyncClient(transport=transport,base_url=settings.downstream_url) as client:
            response=await client.get(f'/products/{product_id}')
        return Product(**response.json())
    return app
''')
    result=asyncio.run(evaluate_full(tmp_path))
    assert 'error' not in result
    assert result['clean_qualified']

    module_name = 'generated_loader_regression'
    sys.modules.pop(module_name, None)
    metadata, rows = asyncio.run(evaluate_pilot(tmp_path))
    assert metadata['clean_qualified']
    assert len(rows) == 6
    loaded_module = sys.modules[module_name]
    assert loaded_module.Product.__module__ == module_name
    try:
        metadata, rows = asyncio.run(evaluate_pilot(tmp_path))
        assert metadata['clean_qualified']
        assert len(rows) == 6
        assert sys.modules[module_name] is not loaded_module
    finally:
        sys.modules.pop(module_name, None)


def test_full_evaluator_reloads_module_between_scenarios(tmp_path):
    (tmp_path/'metadata.json').write_text(json.dumps({
        'artifact_id': 'global_state_regression',
        'task': 'T1',
        'condition': 'C0',
        'model_provider': 'Test',
        'model_family': 'Test',
        'model_version': 'Test',
        'generation_index': 1,
    }))
    (tmp_path/'raw_response.json').write_text('{}')
    (tmp_path/'app.py').write_text('''from benchmark.fixtures.t1 import create_app as reference
calls = 0
def create_app(transport, settings=None):
    global calls
    calls += 1
    kind = 'reference_naive' if calls == 1 else 'reference_resilient'
    return reference(kind, transport, settings)
''')
    result=asyncio.run(evaluate_full(tmp_path))
    assert result['clean_qualified']
    assert not result['primary_pass']
    transient = next(row for row in result['observations'] if row['scenario'] == 'transient_503')
    assert transient['outcome_class'] != 'resilient_success'
