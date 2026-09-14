import asyncio
from dataclasses import dataclass

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from benchmark.timeout_guard import evaluate_timeout_guard


def no_timeout_factory(transport, settings):
    app = FastAPI()

    @app.get("/products/{product_id}")
    async def product(product_id: int):
        async with httpx.AsyncClient(
            transport=transport,
            base_url=settings.downstream_url,
            timeout=None,
        ) as client:
            await client.get(f"/products/{product_id}")
        return {"id": product_id, "name": "fabricated", "price": 1.0}

    return app


def asyncio_timeout_factory(transport, settings):
    app = FastAPI()

    @app.get("/products/{product_id}")
    async def product(product_id: int):
        async with httpx.AsyncClient(
            transport=transport,
            base_url=settings.downstream_url,
            timeout=None,
        ) as client:
            try:
                await asyncio.wait_for(
                    client.get(f"/products/{product_id}"), settings.timeout_s
                )
            except (TimeoutError, httpx.HTTPError):
                return JSONResponse({"detail": "dependency timeout"}, status_code=503)
        return {"id": product_id, "name": "fabricated", "price": 1.0}

    return app


def httpx_timeout_factory(transport, settings):
    app = FastAPI()

    @app.get("/products/{product_id}")
    async def product(product_id: int):
        async with httpx.AsyncClient(
            transport=transport,
            base_url=settings.downstream_url,
            timeout=settings.timeout_s,
        ) as client:
            try:
                await client.get(f"/products/{product_id}")
            except httpx.HTTPError:
                return JSONResponse({"detail": "dependency timeout"}, status_code=503)
        return {"id": product_id, "name": "fabricated", "price": 1.0}

    return app


def excessive_combined_timeout_factory(transport, settings):
    app = FastAPI()

    @app.get("/products/{product_id}")
    async def product(product_id: int):
        async with httpx.AsyncClient(
            transport=transport,
            base_url=settings.downstream_url,
            timeout=0.7,
        ) as client:
            for _ in range(3):
                try:
                    await client.get(f"/products/{product_id}")
                except httpx.HTTPError:
                    continue
        return JSONResponse({"detail": "dependency timeout"}, status_code=503)

    return app


def dataclass_payment_timeout_factory(transport, settings):
    @dataclass
    class Order:
        order_id: str
        status: str
        charge_id: str | None = None

    app = FastAPI()
    app.state.orders = {}

    @app.post("/orders/{order_id}/pay")
    async def pay(order_id: str):
        app.state.orders[order_id] = Order(order_id, "PENDING")
        async with httpx.AsyncClient(
            transport=transport,
            base_url=settings.downstream_url,
            timeout=settings.timeout_s,
        ) as client:
            for _ in range(settings.max_attempts):
                try:
                    await client.post(
                        "/charges",
                        json={"order_id": order_id},
                        headers={"Idempotency-Key": f"order:{order_id}"},
                    )
                except httpx.HTTPError:
                    continue
        app.state.orders[order_id] = Order(order_id, "UNRESOLVED")
        return JSONResponse({"detail": "payment timeout"}, status_code=503)

    return app


def unpaid_payment_timeout_factory(transport, settings):
    app = FastAPI()
    app.state.orders = {}

    @app.post("/orders/{order_id}/pay")
    async def pay(order_id: str):
        app.state.orders[order_id] = {"order_id": order_id, "status": "PENDING"}
        async with httpx.AsyncClient(
            transport=transport,
            base_url=settings.downstream_url,
            timeout=settings.timeout_s,
        ) as client:
            for _ in range(settings.max_attempts):
                try:
                    await client.post(
                        "/charges",
                        json={"order_id": order_id},
                        headers={"Idempotency-Key": f"order:{order_id}"},
                    )
                except httpx.HTTPError:
                    continue
        app.state.orders[order_id] = {"order_id": order_id, "status": "UNPAID"}
        return JSONResponse({"detail": "payment timeout"}, status_code=503)

    return app


async def test_missing_per_attempt_timeout_fails_guard():
    result = await evaluate_timeout_guard("T1", no_timeout_factory)
    assert not result["pass"]
    assert result["attempts"][0]["timeout_mode"] == "external_cancellation"
    assert not result["attempts"][0]["bounded"]


async def test_asyncio_timeout_wrapper_passes_guard():
    result = await evaluate_timeout_guard("T1", asyncio_timeout_factory)
    assert result["pass"], result
    assert result["attempts"][0]["timeout_mode"] == "external_cancellation"


async def test_httpx_timeout_configuration_passes_guard():
    result = await evaluate_timeout_guard("T1", httpx_timeout_factory)
    assert result["pass"], result
    assert result["attempts"][0]["timeout_mode"] == "httpx_configuration"


async def test_combined_configured_timeouts_must_fit_whole_request_deadline():
    result = await evaluate_timeout_guard("T1", excessive_combined_timeout_factory)
    assert not result["pass"], result
    assert result["effective_latency_s"] > 1.0


async def test_dataclass_payment_state_passes_timeout_guard():
    result = await evaluate_timeout_guard("T4", dataclass_payment_timeout_factory)
    assert result["pass"], result


async def test_unknown_payment_timeout_cannot_be_marked_unpaid():
    result = await evaluate_timeout_guard("T4", unpaid_payment_timeout_factory)
    assert not result["pass"], result
