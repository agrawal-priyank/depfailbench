import asyncio
import json
import sys

from benchmark.artifact_runner import evaluate as evaluate_pilot
from benchmark.full_eval import evaluate as evaluate_full


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
        return Product(7,'Keyboard',49.5)
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
