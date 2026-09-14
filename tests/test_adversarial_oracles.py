"""Adversarial controls for request-contract and trace-level oracle gaps."""

from __future__ import annotations

import hashlib

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from benchmark.full_eval import evaluate
from benchmark.full_tasks import CONTENT, ITEMS, KEY


def t1_wrong_dependency_request(transport, settings):
    app = FastAPI()

    @app.get("/products/{product_id}")
    async def product(product_id: int):
        async with httpx.AsyncClient(transport=transport, base_url=settings.downstream_url) as client:
            for _ in range(3):
                try:
                    response = await client.post("/wrong", timeout=None)
                except httpx.HTTPError:
                    continue
                if response.status_code == 200:
                    try:
                        body = response.json()
                    except ValueError:
                        return JSONResponse({"detail": "invalid"}, status_code=502)
                    if body == {"id": 7, "name": "Keyboard", "price": 49.5}:
                        return body
                    return JSONResponse({"detail": "invalid"}, status_code=502)
                if response.status_code == 429:
                    return JSONResponse({"detail": "rate limited"}, status_code=503)
            return JSONResponse({"detail": "unavailable"}, status_code=503)

    return app


def t2_ignores_dependency_results(transport, settings):
    app = FastAPI()

    @app.get("/catalog")
    async def catalog():
        async with httpx.AsyncClient(transport=transport, base_url=settings.downstream_url) as client:
            for cursor in ("0", "1", "2"):
                try:
                    await client.get("/pages", params={"cursor": cursor})
                except httpx.HTTPError:
                    pass
        return {"items": ITEMS}

    return app


def t4_wrong_charge_payload(transport, settings):
    app = FastAPI()
    app.state.orders = {}

    @app.post("/orders/{order_id}/pay")
    async def pay(order_id: str):
        app.state.orders[order_id] = {"order_id": order_id, "status": "PENDING"}
        key = f"payment:{order_id}"
        async with httpx.AsyncClient(transport=transport, base_url=settings.downstream_url) as client:
            for _ in range(3):
                try:
                    response = await client.post(
                        "/charges",
                        json={"wrong_order_field": order_id},
                        headers={"Idempotency-Key": key},
                    )
                except httpx.HTTPError:
                    continue
                if response.status_code in {429, 502, 503, 504}:
                    continue
                if response.status_code == 200:
                    try:
                        receipt = response.json()
                    except ValueError:
                        receipt = None
                    if (
                        isinstance(receipt, dict)
                        and isinstance(receipt.get("charge_id"), str)
                        and receipt.get("status") == "captured"
                    ):
                        state = {
                            "order_id": order_id,
                            "status": "PAID",
                            "charge_id": receipt["charge_id"],
                        }
                        app.state.orders[order_id] = state
                        return state
                    break
        app.state.orders[order_id] = {"order_id": order_id, "status": "UNRESOLVED"}
        return JSONResponse(app.state.orders[order_id], status_code=502)

    return app


def t5_fourth_attempt_on_new_path(transport, settings):
    app = FastAPI()

    @app.post("/uploads/{object_key}")
    async def upload(object_key: str, payload: dict):
        content = payload["content"].encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        async with httpx.AsyncClient(transport=transport, base_url=settings.downstream_url) as client:
            for attempt in range(4):
                path = f"/objects/{object_key}" if attempt < 3 else f"/objects/retry-{object_key}"
                try:
                    response = await client.put(path, content=content)
                except httpx.HTTPError:
                    continue
                if response.status_code in {429, 502, 503, 504}:
                    continue
                if response.status_code == 200:
                    try:
                        receipt = response.json()
                    except ValueError:
                        receipt = None
                    if receipt == {"key": object_key, "sha256": digest}:
                        return receipt
                    return JSONResponse({"detail": "invalid receipt"}, status_code=502)
            return JSONResponse({"detail": "unavailable"}, status_code=503)

    return app


@pytest.mark.parametrize(
    "task,factory,expected_clean_qualified",
    [
        ("T1", t1_wrong_dependency_request, False),
        ("T2", t2_ignores_dependency_results, True),
        ("T4", t4_wrong_charge_payload, False),
        ("T5", t5_fourth_attempt_on_new_path, True),
    ],
)
async def test_adversarial_factory_fails_primary_contract(
    task, factory, expected_clean_qualified, tmp_path
):
    import inspect
    import json

    source = inspect.getsource(factory)
    source = source.replace(factory.__name__, "create_app", 1)
    imports = (
        "from __future__ import annotations\n"
        "import hashlib\n"
        "import httpx\n"
        "from fastapi import FastAPI\n"
        "from fastapi.responses import JSONResponse\n"
        "from benchmark.full_tasks import CONTENT, ITEMS, KEY\n\n"
    )
    (tmp_path / "app.py").write_text(imports + source)
    (tmp_path / "metadata.json").write_text(
        json.dumps(
            {
                "artifact_id": f"adversarial_{task}",
                "task": task,
                "condition": "C1",
                "model_provider": "adversarial-control",
                "generation_index": 0,
            }
        )
    )
    (tmp_path / "raw_response.json").write_text("{}")

    result = await evaluate(tmp_path)

    assert result["clean_qualified"] is expected_clean_qualified, result
    assert not result["primary_pass"], result
    assert any(
        obs["outcome_class"] in {"unsafe_failure", "availability_failure"}
        for obs in result["observations"]
    ), result
