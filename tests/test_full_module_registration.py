import asyncio,json
from benchmark.full_eval import evaluate


def test_dataclass_application_import_uses_normal_module_registration(tmp_path):
    (tmp_path/'metadata.json').write_text(json.dumps({'artifact_id':'loader_regression','task':'T1','condition':'C0','model_provider':'Test'}))
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
    result=asyncio.run(evaluate(tmp_path))
    assert 'error' not in result
    assert result['clean_qualified']
